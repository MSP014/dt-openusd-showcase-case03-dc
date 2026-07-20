"""Build a downsampled OpenVDB runtime proxy through Houdini's VDB Resample SOP.

Run with Houdini's ``hython``. Source cache files are read-only inputs; this
tool writes resampled frames and a separate USD wrapper to supplied paths.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import hou

EXTENT_MIN = (-0.23689999, -0.02, -0.5534302)
EXTENT_MAX = (0.23689999, 0.196, 0.02)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-stem", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-stem", required=True)
    parser.add_argument("--wrapper-path", type=Path, required=True)
    parser.add_argument("--source-start", type=int, default=1001)
    parser.add_argument("--runtime-start", type=int, default=1001)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument("--voxel-size", type=float, required=True)
    args = parser.parse_args()
    if args.count < 1 or args.stride < 1 or args.fps <= 0 or args.voxel_size <= 0:
        parser.error("count, stride, fps, and voxel size must be positive")
    return args


def _make_network() -> tuple[hou.SopNode, hou.SopNode]:
    geometry = hou.node("/obj").createNode("geo", "case03_airflow_proxy")
    for node in geometry.children():
        node.destroy()
    source = geometry.createNode("file", "source_vdb")
    resample = geometry.createNode("vdbresample", "resample_density")
    resample.setInput(0, source)
    resample.parm("mode").set("voxelsizeonly")
    resample.parm("order").set("linear")
    resample.parm("rebuild").set(True)
    resample.parm("prune").set(True)
    return source, resample


def _convert_frames(args: argparse.Namespace) -> list[tuple[int, Path]]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_node, resample_node = _make_network()
    resample_node.parm("voxelsize").set(args.voxel_size)
    converted: list[tuple[int, Path]] = []

    for offset in range(args.count):
        source_frame = args.source_start + offset * args.stride
        runtime_frame = args.runtime_start + offset
        source_path = args.source_dir / f"{args.source_stem}.{source_frame}.vdb"
        output_path = args.output_dir / f"{args.output_stem}.{runtime_frame}.vdb"
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing source frame: {source_path}")

        print(
            f"[{offset + 1:02d}/{args.count:02d}] "
            f"{source_path.name} -> {output_path.name}",
            flush=True,
        )
        source_node.parm("file").set(source_path.as_posix())
        resample_node.cook(force=True)
        resample_node.geometry().saveToFile(output_path.as_posix())
        converted.append((runtime_frame, output_path))

    return converted


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def _write_wrapper(args: argparse.Namespace, converted: list[tuple[int, Path]]) -> None:
    args.wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_dir = args.wrapper_path.parent.resolve()
    samples = []
    for runtime_frame, output_path in converted:
        relative_path = Path(
            os.path.relpath(output_path.resolve(), wrapper_dir)
        ).as_posix()
        samples.append(f"            {runtime_frame}: @{relative_path}@,")

    start_frame = converted[0][0]
    end_frame = converted[-1][0]
    fps = _format_number(float(args.fps))
    wrapper = f"""#usda 1.0
(
    defaultPrim = "sim"
    endTimeCode = {end_frame}
    framesPerSecond = {fps}
    metersPerUnit = 1
    startTimeCode = {start_frame}
    timeCodesPerSecond = {fps}
    upAxis = "Y"
)

def Xform "sim"
{{
    def Volume "server_airflow_load_50"
    {{
        float3[] extent = [
            ({EXTENT_MIN[0]}, {EXTENT_MIN[1]}, {EXTENT_MIN[2]}),
            ({EXTENT_MAX[0]}, {EXTENT_MAX[1]}, {EXTENT_MAX[2]}),
        ]
        rel field:density = </sim/server_airflow_load_50/density>

        def OpenVDBAsset "density"
        {{
            uniform token fieldDataType = "float"
            uniform int fieldIndex = 0
            uniform token fieldName = "density"
            asset filePath.timeSamples = {{
{chr(10).join(samples)}
            }}
        }}
    }}
}}
"""
    args.wrapper_path.write_text(wrapper, encoding="utf-8", newline="\n")


def main() -> int:
    args = _parse_args()
    converted = _convert_frames(args)
    _write_wrapper(args, converted)
    total_bytes = sum(path.stat().st_size for _, path in converted)
    print(
        f"Built {len(converted)} frame(s), {total_bytes / (1024 ** 2):.1f} MiB total",
        flush=True,
    )
    print(f"Wrapper: {args.wrapper_path.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
