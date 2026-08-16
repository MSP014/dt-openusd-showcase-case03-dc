"""Real Kit-CAE Streamlines A/B acceptance reproducer for Stage 09 Package B."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from pathlib import Path

REPRODUCER_ROOT = "/DTRS_KitCAE_Reproducer"
CASE_A_ROOT = f"{REPRODUCER_ROOT}/CaseA_NvidiaStaticMixer"
CASE_B_ROOT = f"{REPRODUCER_ROOT}/CaseB_HoudiniVti"
REPRODUCER_VTI_RELATIVE_PATH = Path(
    "airflow_datasets/01_server/02_load_normal/server_airflow_velocity_normal_1001.vti"
)
_PLACEHOLDER_POINTS = (
    (0.0, 0.0, 0.0),
    (0.1, 0.0, 0.0),
    (0.2, 0.0, 0.0),
    (0.3, 0.0, 0.0),
)


@dataclass(frozen=True)
class StreamlinesIntegrationCaseResult:
    """Programmatic acceptance evidence for one real Kit-CAE Streamlines case."""

    case_id: str
    input_label: str
    passed: bool
    fresh_execution: bool
    completion_count_before: int
    completion_count_after: int
    completion_success: bool | None
    authored_basis_curves: bool
    runtime_basis_curves: bool
    curve_count: int
    point_count: int
    placeholder_geometry: bool
    curve_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    source_bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    curve_bounds_intersect_source: bool
    curve_bounds_within_source: bool
    reason: str | None = None


@dataclass(frozen=True)
class StreamlinesIntegrationAcceptanceResult:
    """The A/B boundary deciding whether Package B may return to DTRS authoring."""

    case_a: StreamlinesIntegrationCaseResult
    case_b: StreamlinesIntegrationCaseResult
    cleanup_passed: bool
    cleanup_reason: str | None = None

    @property
    def success(self) -> bool:
        """Require both runtime evidence and teardown of this isolated diagnostic."""

        return self.case_a.passed and self.case_b.passed and self.cleanup_passed

    @property
    def message(self) -> str:
        """State the next debugging boundary without interpreting authored USD
        placeholders."""

        if not self.case_a.passed:
            return (
                "Case A failed: investigate the installed Kit-CAE runtime before "
                "DTRS authoring."
            )
        if not self.case_b.passed:
            return (
                "Case A passed but Case B failed: investigate the Houdini VTI/vel "
                "input contract."
            )
        if not self.cleanup_passed:
            return (
                "Cases A and B passed, but isolated reproducer cleanup failed: "
                f"{self.cleanup_reason}"
            )
        return "Cases A and B passed; isolated reproducer runtime prims were cleaned."


@dataclass(frozen=True)
class _VtiProbe:
    """Direct VTI facts used to prove Case B's velocity-field semantics."""

    path: Path
    origin: tuple[float, float, float]
    spacing: tuple[float, float, float]
    dimensions: tuple[int, int, int]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]]
    field_component_count: int
    field_tuple_count: int


@dataclass(frozen=True)
class _CaseSpec:
    """One fully isolated source/operator/seed contract for the A/B bisect."""

    case_id: str
    input_label: str
    source_path: Path
    dataset_path: str
    field_paths: tuple[str, ...]
    field_names: tuple[str, ...]
    field_component_count: int
    field_tuple_count: int | None
    seed_path: str
    seed_translation: tuple[float, float, float]
    seed_scale: tuple[float, float, float]
    operator_path: str


@dataclass(frozen=True)
class _ReproducerCleanupResult:
    """Teardown evidence for roots owned exclusively by the isolated A/B
    reproducer."""

    passed: bool
    reproducer_root_present_after_cleanup: bool | None
    proof_root_preserved: bool
    reason: str | None = None


class _OperatorCompletionTracker:
    """Own only the event subscriptions needed to prove one fresh CAE execution."""

    def __init__(self, operator_paths: set[str]) -> None:
        self._operator_paths = operator_paths
        self._counts = {path: 0 for path in operator_paths}
        self._success = {path: None for path in operator_paths}
        self._active_paths: set[str] = set()
        self._subscriptions = ()

    def start(self) -> None:
        """Subscribe before each case binds fields so completion has a causal
        baseline."""

        from carb.eventdispatcher import get_eventdispatcher

        dispatcher = get_eventdispatcher()

        def on_begin(event) -> None:
            path = str(event.get("prim_path") or "")
            if path in self._operator_paths:
                self._active_paths.add(path)

        def on_end(event) -> None:
            path = str(event.get("prim_path") or "")
            if path in self._operator_paths:
                self._active_paths.discard(path)
                self._counts[path] += 1
                self._success[path] = bool(event.get("success"))

        self._subscriptions = (
            dispatcher.observe_event(
                event_name="omni.cae.viz@operator_begin",
                on_event=on_begin,
                observer_name="DTRS Stage 09 Streamlines reproducer begin",
            ),
            dispatcher.observe_event(
                event_name="omni.cae.viz@operator_end",
                on_event=on_end,
                observer_name="DTRS Stage 09 Streamlines reproducer end",
            ),
        )

    def count(self, path: str) -> int:
        """Return observed `operator_end` events for one isolated operator."""

        return self._counts.get(path, 0)

    def success(self, path: str) -> bool | None:
        """Return the last `operator_end.success` value, if the operator completed."""

        return self._success.get(path)

    def is_active(self, path: str) -> bool:
        """Return whether the operator is still between its begin and end events."""

        return path in self._active_paths

    def close(self) -> None:
        """Release event guards even when a case fails before geometry is read."""

        subscriptions = self._subscriptions
        self._subscriptions = ()
        for subscription in subscriptions:
            reset = getattr(subscription, "reset", None)
            if reset:
                reset()


def isolated_reproducer_vti_path(asset_root: Path) -> Path:
    """Return the exact Nominal VTI named in the Package B compatibility bisect."""

    return (asset_root / REPRODUCER_VTI_RELATIVE_PATH).resolve()


def derive_isolated_reproducer_seed(
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
    spacing: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    """Place Case B's deterministic UnitSphere at its imported VTI's world centre."""

    minimum, maximum = bounds
    if any(maximum[index] <= minimum[index] for index in range(3)):
        raise ValueError("VTI reproducer requires positive dataset bounds.")
    if any(value <= 0.0 for value in spacing):
        raise ValueError("VTI reproducer requires positive dataset spacing.")
    return (
        tuple((minimum[index] + maximum[index]) / 2.0 for index in range(3)),
        max(spacing) * 4.0,
    )


async def run_streamlines_integration_acceptance_in_kit(
    asset_root: Path,
    *,
    status_callback=None,
) -> StreamlinesIntegrationAcceptanceResult:
    """Execute the two-case Kit runtime bisect without DTRS Streamlines ownership.

    Case A is the installed NVIDIA ``StaticMixer.cgns`` Streamlines pattern.
    Case B is the exact Houdini VTI and ``vel`` field from DTRS. Both cases use
    fresh roots, the same standard Streamlines command, UnitSphere source command,
    field-selection API, explicit enabled trigger, completion event contract, and
    UsdRT output inspection. The function intentionally does not create Flow,
    temporal, or production Streamlines state.
    """

    import carb
    import omni.kit.app
    import omni.usd
    from omni.cae.schema import viz as cae_viz

    app = omni.kit.app.get_app()
    _require_extensions(
        app,
        (
            "omni.cae.delegate.vtk",
            "omni.cae.importer.vtk",
            "omni.cae.importer.cgns",
            "omni.cae.testing",
            "omni.cae.viz",
        ),
    )
    stage = omni.usd.get_context().get_stage()
    if not stage:
        raise RuntimeError(
            "Stage 09 Streamlines integration acceptance requires an open stage."
        )
    if stage.GetPrimAtPath("/DTRS_KitCAE/FlowSimulation").IsValid():
        raise RuntimeError(
            "Detach the full Airflow runtime before the isolated integration "
            "acceptance."
        )

    _clear_isolated_reproducer_roots(stage)
    await _wait_like_installed_streamlines_test(app)
    if status_callback:
        status_callback("Running isolated real Kit-CAE Streamlines cases A and B…")

    tracker = _OperatorCompletionTracker(
        {f"{CASE_A_ROOT}/Streamlines", f"{CASE_B_ROOT}/Streamlines"}
    )
    try:
        tracker.start()
        case_a = await _run_case_safely(
            "A",
            lambda: _prepare_nvidia_static_mixer_case(app),
            app=app,
            stage=stage,
            tracker=tracker,
            cae_viz=cae_viz,
            carb=carb,
        )
        case_b = await _run_case_safely(
            "B",
            lambda: _prepare_houdini_vti_case(app, stage, asset_root),
            app=app,
            stage=stage,
            tracker=tracker,
            cae_viz=cae_viz,
            carb=carb,
        )
    finally:
        tracker.close()
        # The A/B roots are diagnostic-only. Remove them only after their case
        # logs are complete, while deliberately leaving DTRS-owned proof roots
        # available for the following human visual gate.
        cleanup = await _cleanup_isolated_reproducer_roots(stage, app, carb)

    result = StreamlinesIntegrationAcceptanceResult(
        case_a=case_a,
        case_b=case_b,
        cleanup_passed=cleanup.passed,
        cleanup_reason=cleanup.reason,
    )
    state = "PASS" if result.success else "FAIL"
    logger = carb.log_warn if result.success else carb.log_error
    logger(f"DTRS STREAMLINES | INTEGRATION_ACCEPTANCE | {state} | {result.message}")
    if status_callback:
        status_callback(result.message)
    return result


async def run_isolated_vti_streamlines_reproducer_in_kit(
    asset_root: Path,
    *,
    status_callback=None,
) -> StreamlinesIntegrationAcceptanceResult:
    """Keep the existing isolated-reproducer entry point while it runs the A/B gate.

    The DTRS panel deliberately remains unchanged during the recovery bisect. Its
    existing diagnostic action now invokes the complete real-runtime acceptance
    rather than a VTI-only interpretation of authored USD placeholder geometry.
    """

    return await run_streamlines_integration_acceptance_in_kit(
        asset_root,
        status_callback=status_callback,
    )


async def _prepare_nvidia_static_mixer_case(app) -> _CaseSpec:
    """Prepare Case A using the installed Kit-CAE test's exact CGNS source contract."""

    from omni.cae.importer.cgns import import_to_stage
    from omni.cae.testing import get_test_data_path

    source_path = Path(get_test_data_path("StaticMixer.cgns"))
    if not source_path.is_file():
        raise RuntimeError(
            f"Installed Kit-CAE StaticMixer test data is unavailable: {source_path}."
        )
    import_root = f"{CASE_A_ROOT}/StaticMixer"
    await import_to_stage(str(source_path), import_root)
    await _wait_like_installed_streamlines_test(app)
    base_path = f"{import_root}/Base/StaticMixer"
    return _CaseSpec(
        case_id="A",
        input_label="installed NVIDIA StaticMixer.cgns",
        source_path=source_path,
        dataset_path=f"{base_path}/B1_P3",
        field_paths=(
            f"{base_path}/Flow_Solution/VelocityX",
            f"{base_path}/Flow_Solution/VelocityY",
            f"{base_path}/Flow_Solution/VelocityZ",
        ),
        field_names=("VelocityX", "VelocityY", "VelocityZ"),
        field_component_count=3,
        field_tuple_count=None,
        seed_path=f"{CASE_A_ROOT}/UnitSphere",
        seed_translation=(0.0, 0.0, 0.0),
        seed_scale=(0.2, 0.2, 0.2),
        operator_path=f"{CASE_A_ROOT}/Streamlines",
    )


async def _prepare_houdini_vti_case(app, stage, asset_root: Path) -> _CaseSpec:
    """Prepare Case B from the real Nominal VTI without touching DTRS source state."""

    from omni.cae.importer.vtk import import_to_stage
    from omni.cae.schema import cae
    from omni.cae.schema import vtk as cae_vtk
    from pxr import Gf

    source_path = isolated_reproducer_vti_path(asset_root)
    if not source_path.is_file():
        raise RuntimeError(f"Case B VTI is unavailable: {source_path}.")
    probe = _read_vti_probe(source_path)
    import_root = f"{CASE_B_ROOT}/Velocity"
    dataset_path = f"{import_root}/VTKImageData"
    await import_to_stage(str(source_path), import_root)
    await _wait_like_installed_streamlines_test(app)
    dataset_prim = stage.GetPrimAtPath(dataset_path)
    _restore_vti_origin_in_session_layer(stage, dataset_prim, probe.origin, cae_vtk, Gf)
    await _wait_like_installed_streamlines_test(app)
    imported_bounds, imported_spacing = _imported_image_bounds(
        dataset_prim, cae, cae_vtk
    )
    seed_center, seed_radius = derive_isolated_reproducer_seed(
        imported_bounds, imported_spacing
    )
    return _CaseSpec(
        case_id="B",
        input_label="server_airflow_velocity_normal_1001.vti / vel",
        source_path=source_path,
        dataset_path=dataset_path,
        field_paths=(f"{import_root}/PointData/vel",),
        field_names=("vel",),
        field_component_count=probe.field_component_count,
        field_tuple_count=probe.field_tuple_count,
        seed_path=f"{CASE_B_ROOT}/UnitSphere",
        seed_translation=seed_center,
        seed_scale=(seed_radius, seed_radius, seed_radius),
        operator_path=f"{CASE_B_ROOT}/Streamlines",
    )


async def _run_case_safely(
    case_id: str, prepare_case, *, app, stage, tracker, cae_viz, carb
):
    """Keep Case B independently observable even if the known-good Case A fails."""

    try:
        spec = await prepare_case()
        return await _run_case_in_kit(
            spec,
            app=app,
            stage=stage,
            tracker=tracker,
            cae_viz=cae_viz,
            carb=carb,
        )
    except Exception as error:
        result = StreamlinesIntegrationCaseResult(
            case_id=case_id,
            input_label="unprepared",
            passed=False,
            fresh_execution=False,
            completion_count_before=0,
            completion_count_after=0,
            completion_success=None,
            authored_basis_curves=False,
            runtime_basis_curves=False,
            curve_count=0,
            point_count=0,
            placeholder_geometry=False,
            curve_bounds=None,
            source_bounds=None,
            curve_bounds_intersect_source=False,
            curve_bounds_within_source=False,
            reason=str(error),
        )
        carb.log_error(_case_result_log(result, None))
        return result


async def _run_case_in_kit(
    spec: _CaseSpec, *, app, stage, tracker, cae_viz, carb
) -> StreamlinesIntegrationCaseResult:
    """Author, trigger, and inspect one case through the real Kit/UsdRT path."""

    import numpy as np
    import warp as wp
    from omni.cae.data import usd_utils as cae_usd_utils
    from omni.cae.data.commands import execute_command
    from omni.cae.dav import probe_fields
    from omni.cae.viz import utils as cae_viz_utils
    from pxr import Usd, UsdGeom
    from usdrt import UsdGeom as UsdGeomRT

    await execute_command(
        "CreateCaeVizStreamlines",
        dataset_path=spec.dataset_path,
        prim_path=spec.operator_path,
        type="standard",
    )
    await execute_command(
        "CreateCaeVizMeshPrim",
        prim_type="UnitSphere",
        prim_path=spec.seed_path,
    )
    await execute_command(
        "TransformPrimSRT",
        path=spec.seed_path,
        new_translation=list(spec.seed_translation),
        new_scale=list(spec.seed_scale),
    )
    await _wait_like_installed_streamlines_test(app)

    operator_prim = stage.GetPrimAtPath(spec.operator_path)
    seed_prim = stage.GetPrimAtPath(spec.seed_path)
    field_prims = tuple(stage.GetPrimAtPath(path) for path in spec.field_paths)
    if (
        not operator_prim.IsValid()
        or not seed_prim.IsValid()
        or not all(prim.IsValid() for prim in field_prims)
    ):
        raise RuntimeError(
            "Kit-CAE could not author the requested dataset, seed, operator, or "
            "velocity field."
        )

    # Explicit disable/enable gives this test a fresh-execution boundary. The
    # creation command can otherwise run before selector targets exist; this is
    # causal test control, not a Streamlines seed, width, or timing adjustment.
    operator_api = cae_viz.OperatorAPI(operator_prim)
    operator_api.CreateEnabledAttr().Set(False)
    completion_count_before = tracker.count(spec.operator_path)
    streamlines_api = cae_viz.StreamlinesAPI(operator_prim)
    streamlines_api.GetDirectionAttr().Set(cae_viz.Tokens.forward)
    cae_viz.DatasetSelectionAPI(operator_prim, "seeds").GetTargetRel().SetTargets(
        {seed_prim.GetPath()}
    )
    cae_viz.FieldSelectionAPI(operator_prim, "velocities").GetTargetRel().SetTargets(
        [prim.GetPath() for prim in field_prims]
    )

    source_facts = await _collect_source_facts(
        stage,
        operator_prim,
        seed_prim,
        spec,
        cae_viz_utils,
        probe_fields,
        Usd,
        UsdGeom,
        np,
    )
    carb.log_warn(_case_pre_execution_log(spec, source_facts, streamlines_api))

    operator_api.CreateEnabledAttr().Set(True)
    # This is the exact post-binding settle window used by NVIDIA's installed
    # Streamlines test. The event wait below then proves that the settled result
    # belongs to this enable transition rather than to creation-time defaults.
    await _wait_like_installed_streamlines_test(app)
    completion_count_after = await _wait_for_fresh_completion(
        app, tracker, spec.operator_path, completion_count_before
    )
    fresh_execution = completion_count_after > completion_count_before
    completion_success = tracker.success(spec.operator_path)
    authored_curves = UsdGeom.BasisCurves(operator_prim)
    authored_basis_curves = authored_curves.GetPrim().IsValid()
    authored_points = authored_curves.GetPointsAttr().Get() or ()
    rt_curves = UsdGeomRT.BasisCurves(cae_usd_utils.get_prim_rt(operator_prim))
    runtime_basis_curves = rt_curves.GetPrim().IsValid()
    points = (
        _read_usdrt_points(rt_curves.GetPointsAttr(), wp)
        if runtime_basis_curves
        else ()
    )
    curve_vertex_counts = (
        _read_usdrt_ints(rt_curves.GetCurveVertexCountsAttr(), wp)
        if runtime_basis_curves
        else ()
    )
    curve_bounds = _point_bounds(points)
    placeholder_geometry = _is_create_command_placeholder(points, curve_vertex_counts)
    source_bounds = source_facts["dataset_bounds"]
    intersects_source = _bounds_intersect(curve_bounds, source_bounds)
    within_source = _bounds_within(curve_bounds, source_bounds)
    passed = (
        fresh_execution
        and completion_success is True
        and runtime_basis_curves
        and not placeholder_geometry
        and len(curve_vertex_counts) > 0
        and len(points) > 4
        and intersects_source
    )
    reason = (
        None
        if passed
        else (
            "Runtime output did not satisfy fresh-execution, UsdRT geometry, or "
            "source-domain acceptance."
        )
    )
    result = StreamlinesIntegrationCaseResult(
        case_id=spec.case_id,
        input_label=spec.input_label,
        passed=passed,
        fresh_execution=fresh_execution,
        completion_count_before=completion_count_before,
        completion_count_after=completion_count_after,
        completion_success=completion_success,
        authored_basis_curves=authored_basis_curves,
        runtime_basis_curves=runtime_basis_curves,
        curve_count=len(curve_vertex_counts),
        point_count=len(points),
        placeholder_geometry=placeholder_geometry,
        curve_bounds=curve_bounds,
        source_bounds=source_bounds,
        curve_bounds_intersect_source=intersects_source,
        curve_bounds_within_source=within_source,
        reason=reason,
    )
    logger = carb.log_warn if passed else carb.log_error
    logger(
        _case_result_log(
            result, source_facts, authored_point_count=len(authored_points)
        )
    )
    return result


async def _collect_source_facts(
    stage,
    operator_prim,
    seed_prim,
    spec,
    cae_viz_utils,
    probe_fields,
    Usd,
    UsdGeom,
    np,
):
    """Collect exact source and seed evidence before the operator is enabled."""

    from omni.cae.viz.create_commands import DatasetHelper

    helper = await DatasetHelper.init(stage, [spec.dataset_path])
    source_bounds = _range_bounds(helper.bounds)
    seed_world_bounds = _prim_world_bounds(seed_prim, Usd, UsdGeom)
    source_dataset = await cae_viz_utils.get_input_dataset(
        operator_prim,
        "source",
        timeCode=Usd.TimeCode.EarliestTime(),
        device="cuda:0",
        required_fields={"velocities"},
    )
    seed_dataset = await cae_viz_utils.get_input_dataset(
        operator_prim,
        "seeds",
        timeCode=Usd.TimeCode.EarliestTime(),
        device="cuda:0",
        needs_topology=False,
        needs_fields=False,
    )
    probed_seed_dataset = probe_fields(
        source_dataset, seed_dataset, fields={"velocities"}
    )
    velocity_values = np.asarray(
        probed_seed_dataset.get_field("velocities").get_data().numpy()
    )
    velocity_vectors = velocity_values.reshape(-1, spec.field_component_count)
    magnitudes = np.linalg.norm(velocity_vectors, axis=1)
    field_associations = tuple(
        str(stage.GetPrimAtPath(path).GetAttribute("fieldAssociation").Get())
        for path in spec.field_paths
    )
    return {
        "dataset_bounds": source_bounds,
        "seed_world_bounds": seed_world_bounds,
        "seed_center_inside_dataset": _point_within(
            spec.seed_translation, source_bounds
        ),
        "seed_bounds_intersect_dataset": _bounds_intersect(
            seed_world_bounds, source_bounds
        ),
        "field_associations": field_associations,
        "velocity_magnitude_near_seed": (
            float(magnitudes.min()),
            float(magnitudes.mean()),
            float(magnitudes.max()),
        ),
        "field_tuple_count": spec.field_tuple_count or int(helper.nb_points),
    }


async def _wait_for_fresh_completion(
    app, tracker, operator_path: str, completion_count_before: int
) -> int:
    """Wait through Kit updates until a post-binding `operator_end` event arrives."""

    deadline = time.monotonic() + 10.0
    while True:
        completion_count = tracker.count(operator_path)
        if completion_count > completion_count_before and not tracker.is_active(
            operator_path
        ):
            return completion_count
        if time.monotonic() >= deadline:
            return completion_count
        await app.next_update_async()
        await asyncio.sleep(0.01)


async def _wait_like_installed_streamlines_test(app, cycles: int = 10) -> None:
    """Use the same ten-update settling window as Kit-CAE ``test_streamlines.py``."""

    for _ in range(cycles):
        await app.next_update_async()
        await asyncio.sleep(0.01)


def _read_vti_probe(vti_path: Path) -> _VtiProbe:
    """Read direct VTI metadata without using any DTRS source helper."""

    from vtkmodules.vtkIOXML import vtkXMLImageDataReader

    reader = vtkXMLImageDataReader()
    reader.SetFileName(str(vti_path))
    reader.Update()
    image = reader.GetOutput()
    velocities = image.GetPointData().GetArray("vel")
    if velocities is None:
        raise RuntimeError("Case B VTI has no PointData vector field named 'vel'.")
    bounds = image.GetBounds()
    return _VtiProbe(
        path=vti_path,
        origin=tuple(float(value) for value in image.GetOrigin()),
        spacing=tuple(float(value) for value in image.GetSpacing()),
        dimensions=tuple(int(value) for value in image.GetDimensions()),
        bounds=(
            tuple(float(bounds[index]) for index in (0, 2, 4)),
            tuple(float(bounds[index]) for index in (1, 3, 5)),
        ),
        field_component_count=int(velocities.GetNumberOfComponents()),
        field_tuple_count=int(velocities.GetNumberOfTuples()),
    )


def _restore_vti_origin_in_session_layer(
    stage, dataset_prim, origin, cae_vtk, Gf
) -> None:
    """Retain the accepted Stage 6 origin shim inside Case B's private root."""

    if not dataset_prim.IsValid():
        raise RuntimeError("Case B VTI import did not author a VTKImageData dataset.")
    previous_target = stage.GetEditTarget()
    stage.SetEditTarget(stage.GetSessionLayer())
    try:
        origin_attr = cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr()
        if not origin_attr or not origin_attr.IsValid():
            raise RuntimeError(
                "Case B VTKImageData has no ImageDataAPI.origin attribute."
            )
        origin_attr.Set(Gf.Vec3f(*origin))
    finally:
        stage.SetEditTarget(previous_target)


def _imported_image_bounds(dataset_prim, cae, cae_vtk):
    """Return Case B bounds after its private origin opinion is applied."""

    if not dataset_prim.IsA(cae.DataSet) or not dataset_prim.HasAPI(cae.DenseVolumeAPI):
        raise RuntimeError(
            "Case B VTI import did not produce the expected DenseVolume dataset."
        )
    dense_volume = cae.DenseVolumeAPI(dataset_prim)
    minimum_extent = dense_volume.GetMinExtentAttr().Get()
    maximum_extent = dense_volume.GetMaxExtentAttr().Get()
    spacing = tuple(float(value) for value in dense_volume.GetSpacingAttr().Get())
    origin = tuple(
        float(value)
        for value in cae_vtk.ImageDataAPI(dataset_prim).GetOriginAttr().Get()
    )
    return (
        (
            tuple(
                origin[index] + minimum_extent[index] * spacing[index]
                for index in range(3)
            ),
            tuple(
                origin[index] + maximum_extent[index] * spacing[index]
                for index in range(3)
            ),
        ),
        spacing,
    )


def _range_bounds(
    bounds,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Normalise Kit/pxr bounds to logging and assertion-friendly Python tuples."""

    return (
        tuple(float(value) for value in bounds.GetMin()),
        tuple(float(value) for value in bounds.GetMax()),
    )


def _prim_world_bounds(seed_prim, Usd, UsdGeom):
    """Read actual transformed UnitSphere bounds, not only requested SRT values."""

    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    return _range_bounds(cache.ComputeWorldBound(seed_prim).ComputeAlignedRange())


def _read_usdrt_points(attribute, wp) -> tuple[tuple[float, float, float], ...]:
    """Read points written by Kit-CAE's runtime representation, not USD's
    placeholder."""

    if not attribute.IsValid():
        return ()
    if attribute.IsGpuDataValid():
        data = wp.array(attribute.Get()).numpy()
    elif attribute.IsCpuDataValid():
        attribute.SyncDataToGpu()
        data = wp.array(attribute.Get()).numpy()
    else:
        return ()
    return tuple(tuple(float(value) for value in point) for point in data)


def _read_usdrt_ints(attribute, wp) -> tuple[int, ...]:
    """Read runtime curve counts without falling back to authored USD values."""

    if not attribute.IsValid():
        return ()
    if attribute.IsGpuDataValid():
        data = wp.array(attribute.Get()).numpy()
    elif attribute.IsCpuDataValid():
        attribute.SyncDataToGpu()
        data = wp.array(attribute.Get()).numpy()
    else:
        return ()
    return tuple(int(value) for value in data.reshape(-1))


def _is_create_command_placeholder(points, curve_vertex_counts) -> bool:
    """Identify the exact four-point geometry authored before a real execution
    exists."""

    return (
        curve_vertex_counts == (4,)
        and len(points) == len(_PLACEHOLDER_POINTS)
        and all(
            math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6)
            for point, placeholder in zip(points, _PLACEHOLDER_POINTS)
            for actual, expected in zip(point, placeholder)
        )
    )


def _point_bounds(points):
    """Return a finite point extent, or ``None`` when the runtime output is empty."""

    if not points:
        return None
    return (
        tuple(min(point[index] for point in points) for index in range(3)),
        tuple(max(point[index] for point in points) for index in range(3)),
    )


def _point_within(point, bounds) -> bool:
    """Return whether a seed centre lies in the inclusive source domain."""

    if bounds is None:
        return False
    minimum, maximum = bounds
    return all(minimum[index] <= point[index] <= maximum[index] for index in range(3))


def _bounds_intersect(left, right) -> bool:
    """Return whether two finite axis-aligned domains share any volume or boundary."""

    if left is None or right is None:
        return False
    return all(
        left[0][index] <= right[1][index] and left[1][index] >= right[0][index]
        for index in range(3)
    )


def _bounds_within(inner, outer) -> bool:
    """Return whether every generated point bound remains inside the source domain."""

    if inner is None or outer is None:
        return False
    return all(
        outer[0][index] <= inner[0][index] and inner[1][index] <= outer[1][index]
        for index in range(3)
    )


def _case_pre_execution_log(spec: _CaseSpec, facts, streamlines_api) -> str:
    """Format concise pre-enable evidence for a human review of either test case."""

    return "\n".join(
        (
            f"DTRS STREAMLINES | INTEGRATION_CASE_{spec.case_id} | PREPARED",
            "",
            f"input={spec.input_label}",
            f"source={spec.source_path}",
            f"dataset_bounds={facts['dataset_bounds']}",
            f"velocity_field_names={spec.field_names}",
            f"velocity_field_associations={facts['field_associations']}",
            f"velocity_field_component_count={spec.field_component_count}",
            f"velocity_field_tuple_count={facts['field_tuple_count']}",
            "",
            "seed:",
            f"  world_bounds={facts['seed_world_bounds']}",
            f"  center_inside_dataset={facts['seed_center_inside_dataset']}",
            f"  bounds_intersect_dataset={facts['seed_bounds_intersect_dataset']}",
            (
                "  velocity_magnitude_near_seed_min_mean_max="
                f"{facts['velocity_magnitude_near_seed']}"
            ),
            "",
            "integration:",
            f"  direction={streamlines_api.GetDirectionAttr().Get()}",
            f"  min_step_size={streamlines_api.GetMinStepSizeAttr().Get()}",
            f"  initial_step_size={streamlines_api.GetInitialStepSizeAttr().Get()}",
            f"  max_step_size={streamlines_api.GetMaxStepSizeAttr().Get()}",
            f"  max_steps={streamlines_api.GetMaxStepsAttr().Get()}",
            f"  tolerance={streamlines_api.GetToleranceAttr().Get()}",
        )
    )


def _case_result_log(
    result: StreamlinesIntegrationCaseResult,
    facts,
    *,
    authored_point_count: int | None = None,
) -> str:
    """Keep the outcome reviewable without USD tree inspection or raw event dumps."""

    state = "PASS" if result.passed else "FAIL"
    lines = [
        f"DTRS STREAMLINES | INTEGRATION_CASE_{result.case_id} | {state}",
        "",
        f"input={result.input_label}",
        "operator:",
        f"  completion_count_before={result.completion_count_before}",
        f"  completion_count_after={result.completion_count_after}",
        f"  fresh_execution={result.fresh_execution}",
        f"  completion_success={result.completion_success}",
        "geometry:",
        f"  authored_basis_curves={result.authored_basis_curves}",
        f"  authored_usd_point_count={authored_point_count}",
        f"  runtime_usdrt_basis_curves={result.runtime_basis_curves}",
        f"  runtime_curve_count={result.curve_count}",
        f"  runtime_point_count={result.point_count}",
        f"  placeholder_geometry={result.placeholder_geometry}",
        f"  curve_bounds={result.curve_bounds}",
        f"  source_bounds={result.source_bounds}",
        f"  curve_bounds_intersect_source={result.curve_bounds_intersect_source}",
        f"  curve_bounds_within_source={result.curve_bounds_within_source}",
    ]
    if facts:
        lines.extend(("seed:", f"  world_bounds={facts['seed_world_bounds']}"))
    if result.reason:
        lines.extend(("", f"reason={result.reason}"))
    return "\n".join(lines)


def _require_extensions(app, extension_ids: tuple[str, ...]) -> None:
    """Fail explicitly when this isolated proof lacks an installed test dependency."""

    manager = app.get_extension_manager()
    disabled = [
        extension_id
        for extension_id in extension_ids
        if not manager.is_extension_enabled(extension_id)
    ]
    if disabled:
        raise RuntimeError(
            "Integration acceptance requires enabled extensions: " + ", ".join(disabled)
        )


def _clear_isolated_reproducer_roots(stage) -> None:
    """Remove only prior A/B roots from both potential authoring layers."""

    previous_target = stage.GetEditTarget()
    try:
        for layer in (stage.GetSessionLayer(), stage.GetRootLayer()):
            stage.SetEditTarget(layer)
            if stage.GetPrimAtPath(REPRODUCER_ROOT).IsValid():
                stage.RemovePrim(REPRODUCER_ROOT)
    finally:
        stage.SetEditTarget(previous_target)


async def _cleanup_isolated_reproducer_roots(
    stage, app, carb
) -> _ReproducerCleanupResult:
    """Tear down the A/B reproducer without touching the DTRS proof ownership tree."""

    proof_path = "/DTRS_KitCAE/Streamlines/StaticVelocityProof"
    proof_root_was_present = stage.GetPrimAtPath(proof_path).IsValid()
    reproducer_root_present = None
    try:
        _clear_isolated_reproducer_roots(stage)
        # Removing a USD root is immediate, but one Kit update lets Fabric and
        # Hydra consume that removal before control returns to the visual gate.
        await app.next_update_async()
        reproducer_root_present = stage.GetPrimAtPath(REPRODUCER_ROOT).IsValid()
        proof_root_preserved = (
            stage.GetPrimAtPath(proof_path).IsValid() == proof_root_was_present
        )
        passed = not reproducer_root_present and proof_root_preserved
        reason = None
        if reproducer_root_present:
            reason = f"{REPRODUCER_ROOT} still exists after cleanup"
        elif not proof_root_preserved:
            reason = "DTRS StaticVelocityProof root changed during reproducer cleanup"
    except Exception as error:
        passed = False
        proof_root_preserved = False
        reason = str(error)

    state = "PASS" if passed else "FAIL"
    logger = carb.log_warn if passed else carb.log_error
    logger(
        f"DTRS STREAMLINES | INTEGRATION_CLEANUP | {state}\n"
        f"reproducer_root={REPRODUCER_ROOT}\n"
        f"reproducer_root_present_after_cleanup={reproducer_root_present}\n"
        f"dtrs_static_proof_root_preserved={proof_root_preserved}"
        + (f"\nreason={reason}" if reason else "")
    )
    return _ReproducerCleanupResult(
        passed=passed,
        reproducer_root_present_after_cleanup=reproducer_root_present,
        proof_root_preserved=proof_root_preserved,
        reason=reason,
    )
