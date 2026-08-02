import hou
import os
import math
import tempfile
import subprocess
import numpy as np


CONDA_PYTHON = r"C:\Users\SpeLL\anaconda3\envs\case03-env\python.exe"

EXPECTED_RESOLUTION = (184, 72, 232)
EXPECTED_VOXEL_SIZE = 0.00255
VOXEL_SIZE_TOLERANCE = 1e-5


# ============================================================
# Resolve this PDG work item
# ============================================================

frame = int(round(work_item.frame))
inputs = work_item.inputFiles

if len(inputs) != 1:
    raise RuntimeError(
        f"Frame {frame}: expected exactly 1 input file, "
        f"got {len(inputs)}"
    )

input_path = inputs[0].local_path

expected_name = f"vel_{frame:04d}.bgeo.sc"
actual_name = os.path.basename(input_path)

if actual_name != expected_name:
    raise RuntimeError(
        f"PDG input mismatch:\n"
        f"Frame: {frame}\n"
        f"Expected: {expected_name}\n"
        f"Actual: {actual_name}\n"
        f"Path: {input_path}"
    )

if not os.path.isfile(input_path):
    raise RuntimeError(
        f"Frame {frame}: input cache does not exist:\n"
        f"{input_path}"
    )


# ============================================================
# Load cached Houdini geometry
# ============================================================

geo = hou.Geometry()

try:
    geo.loadFromFile(input_path)
except Exception as exc:
    raise RuntimeError(
        f"Frame {frame}: failed to load Houdini cache:\n"
        f"{input_path}\n\n"
        f"{exc}"
    ) from exc


# ============================================================
# Find velocity VDB
# ============================================================

vel_prim = None

for prim in geo.prims():
    if isinstance(prim, hou.VDB):
        try:
            name = prim.attribValue("name")
        except Exception:
            continue

        if name == "vel":
            vel_prim = prim
            break

if vel_prim is None:
    raise RuntimeError(
        f"Frame {frame}: vector VDB 'vel' was not found in:\n"
        f"{input_path}"
    )


# ============================================================
# Validate Houdini-side runtime cache contract
# ============================================================

nx, ny, nz = tuple(
    int(v) for v in vel_prim.resolution()
)

resolution = (nx, ny, nz)

if resolution != EXPECTED_RESOLUTION:
    raise RuntimeError(
        f"Frame {frame}: unexpected VDB resolution:\n"
        f"Expected: {EXPECTED_RESOLUTION}\n"
        f"Actual: {resolution}"
    )


spacing = tuple(
    float(v) for v in vel_prim.voxelSize()
)

for axis, value in zip("XYZ", spacing):

    if not math.isfinite(value) or value <= 0.0:
        raise RuntimeError(
            f"Frame {frame}: invalid voxel size on {axis}: "
            f"{value}"
        )

    if abs(value - EXPECTED_VOXEL_SIZE) > VOXEL_SIZE_TOLERANCE:
        raise RuntimeError(
            f"Frame {frame}: unexpected voxel size on {axis}:\n"
            f"Expected: ~{EXPECTED_VOXEL_SIZE}\n"
            f"Actual: {value}"
        )


origin = tuple(
    float(v)
    for v in vel_prim.indexToPos((0, 0, 0))
)

for axis, value in zip("XYZ", origin):
    if not math.isfinite(value):
        raise RuntimeError(
            f"Frame {frame}: invalid VDB origin on {axis}: "
            f"{value}"
        )


# ============================================================
# Output paths
#
# VTI_Writer writes into a neutral Houdini-side staging
# directory. Publishing into a specific runtime dataset
# (server/load_normal/etc.) is handled separately.
# ============================================================

hip_dir = hou.expandString("$HIP")

output_dir = os.path.normpath(
    os.path.join(
        hip_dir,
        "geo",
        "vti",
    )
)

os.makedirs(
    output_dir,
    exist_ok=True,
)


output_path = os.path.join(
    output_dir,
    f"server_airflow_velocity_{frame:04d}.vti",
)

# Write to a temporary file first.
# Only a completely successful export gets the final .vti name.
output_stem, output_ext = os.path.splitext(output_path)

temp_output_path = (
    output_stem
    + ".tmp"
    + output_ext
)


# Remove debris from an interrupted earlier run.
if os.path.isfile(temp_output_path):
    os.remove(temp_output_path)


# ============================================================
# Read VDB into float32 NumPy array
#
# One Z slice at a time so Houdini does not create all
# hou.Vector3 objects simultaneously.
# ============================================================

voxel_count = nx * ny * nz
slice_size = nx * ny

velocities = np.empty(
    (voxel_count, 3),
    dtype=np.float32,
)


for z in range(nz):

    vectors = vel_prim.voxelRangeAsVector3(
        hou.BoundingBox(
            0,
            0,
            z,
            nx,
            ny,
            z + 1,
        )
    )

    slice_array = np.asarray(
        [tuple(v) for v in vectors],
        dtype=np.float32,
    )

    expected_slice_shape = (
        slice_size,
        3,
    )

    if slice_array.shape != expected_slice_shape:
        raise RuntimeError(
            f"Frame {frame}: unexpected velocity slice "
            f"shape at Z={z}:\n"
            f"Expected: {expected_slice_shape}\n"
            f"Actual: {slice_array.shape}"
        )

    start = z * slice_size
    end = start + slice_size

    velocities[start:end] = slice_array


# Final NumPy-side contract check before handing data to VTK.
expected_velocity_shape = (
    voxel_count,
    3,
)

if velocities.shape != expected_velocity_shape:
    raise RuntimeError(
        f"Frame {frame}: velocity array shape mismatch:\n"
        f"Expected: {expected_velocity_shape}\n"
        f"Actual: {velocities.shape}"
    )

if velocities.dtype != np.float32:
    raise RuntimeError(
        f"Frame {frame}: velocity dtype mismatch:\n"
        f"Expected: float32\n"
        f"Actual: {velocities.dtype}"
    )


# ============================================================
# Houdini -> external case03-env / VTK bridge
# ============================================================

with tempfile.TemporaryDirectory(
    prefix=f"case03_velocity_{frame}_"
) as temp_dir:

    npy_path = os.path.join(
        temp_dir,
        "velocity.npy",
    )

    np.save(
        npy_path,
        velocities,
    )

    # Free the large Houdini-side NumPy allocation before
    # starting the VTK subprocess.
    del velocities


    vtk_code = r'''
import sys
import os
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk


npy_path = sys.argv[1]
output_path = sys.argv[2]

nx = int(sys.argv[3])
ny = int(sys.argv[4])
nz = int(sys.argv[5])

origin = (
    float(sys.argv[6]),
    float(sys.argv[7]),
    float(sys.argv[8]),
)

spacing = (
    float(sys.argv[9]),
    float(sys.argv[10]),
    float(sys.argv[11]),
)


# ============================================================
# Load NumPy bridge data
# ============================================================

vectors = np.load(npy_path)

expected_shape = (
    nx * ny * nz,
    3,
)

if vectors.shape != expected_shape:
    raise RuntimeError(
        f"Velocity shape mismatch: "
        f"{vectors.shape} != {expected_shape}"
    )

if vectors.dtype != np.float32:
    raise RuntimeError(
        f"Velocity dtype mismatch: "
        f"{vectors.dtype} != float32"
    )


# ============================================================
# Build vtkImageData
# ============================================================

image = vtk.vtkImageData()

image.SetDimensions(
    nx,
    ny,
    nz,
)

image.SetOrigin(
    *origin
)

image.SetSpacing(
    *spacing
)


vtk_vectors = numpy_to_vtk(
    np.ascontiguousarray(vectors),
    deep=True,
    array_type=vtk.VTK_FLOAT,
)

vtk_vectors.SetName("vel")
vtk_vectors.SetNumberOfComponents(3)

image.GetPointData().SetVectors(
    vtk_vectors
)


# ============================================================
# Cheap in-memory VTI contract validation
#
# This validates the data we are about to write.
# It does NOT read the finished VTI back from disk.
# ============================================================

actual_dims = tuple(
    int(v)
    for v in image.GetDimensions()
)

expected_dims = (
    nx,
    ny,
    nz,
)

if actual_dims != expected_dims:
    raise RuntimeError(
        f"vtkImageData dimensions mismatch: "
        f"{actual_dims} != {expected_dims}"
    )


actual_origin = tuple(
    float(v)
    for v in image.GetOrigin()
)

for axis, actual, expected in zip(
    "XYZ",
    actual_origin,
    origin,
):
    if abs(actual - expected) > 1e-8:
        raise RuntimeError(
            f"vtkImageData origin {axis} mismatch: "
            f"{actual} != {expected}"
        )


actual_spacing = tuple(
    float(v)
    for v in image.GetSpacing()
)

for axis, actual, expected in zip(
    "XYZ",
    actual_spacing,
    spacing,
):
    if abs(actual - expected) > 1e-8:
        raise RuntimeError(
            f"vtkImageData spacing {axis} mismatch: "
            f"{actual} != {expected}"
        )


point_data = image.GetPointData()

vel = point_data.GetArray("vel")

if vel is None:
    raise RuntimeError(
        "vtkImageData PointData array 'vel' "
        "was not created."
    )


if vel.GetNumberOfComponents() != 3:
    raise RuntimeError(
        f"'vel' component count mismatch: "
        f"{vel.GetNumberOfComponents()} != 3"
    )


expected_tuples = (
    nx * ny * nz
)

if vel.GetNumberOfTuples() != expected_tuples:
    raise RuntimeError(
        f"'vel' tuple count mismatch: "
        f"{vel.GetNumberOfTuples()} != {expected_tuples}"
    )


if vel.GetDataType() != vtk.VTK_FLOAT:
    raise RuntimeError(
        f"'vel' data type mismatch: "
        f"{vel.GetDataTypeAsString()} != float"
    )


# ============================================================
# Write compressed VTI
# ============================================================

writer = vtk.vtkXMLImageDataWriter()

writer.SetFileName(
    output_path
)

writer.SetInputData(
    image
)

writer.SetDataModeToAppended()
writer.SetCompressorTypeToZLib()

result = writer.Write()

if result != 1:
    raise RuntimeError(
        f"VTK failed to write '{output_path}'"
    )


if not os.path.isfile(output_path):
    raise RuntimeError(
        f"VTK reported success but file does not exist: "
        f"'{output_path}'"
    )


file_size = os.path.getsize(output_path)

if file_size <= 0:
    raise RuntimeError(
        f"VTK produced an empty file: "
        f"'{output_path}'"
    )


print(
    f"VALID "
    f"dims={nx}x{ny}x{nz} "
    f"tuples={expected_tuples} "
    f"components=3 "
    f"dtype=float "
    f"bytes={file_size}"
)
'''


    # Houdini's embedded Python environment must not
    # contaminate the external Conda interpreter.
    env = os.environ.copy()

    env.pop(
        "PYTHONHOME",
        None,
    )

    env.pop(
        "PYTHONPATH",
        None,
    )


    subprocess_kwargs = {
        "args": [
            CONDA_PYTHON,
            "-c",
            vtk_code,
            npy_path,
            temp_output_path,
            str(nx),
            str(ny),
            str(nz),
            str(origin[0]),
            str(origin[1]),
            str(origin[2]),
            str(spacing[0]),
            str(spacing[1]),
            str(spacing[2]),
        ],
        "capture_output": True,
        "text": True,
        "env": env,

        # Generous safety ceiling.
        # Normal export currently takes roughly 2–3 min.
        "timeout": 1800,
    }


    # Prevent case03-env from opening a separate console
    # window for every PDG work item on Windows.
    if os.name == "nt":
        subprocess_kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW
        )


    try:
        result = subprocess.run(
            **subprocess_kwargs
        )

    except subprocess.TimeoutExpired as exc:

        if os.path.isfile(temp_output_path):
            os.remove(temp_output_path)

        raise RuntimeError(
            f"Frame {frame}: VTI export exceeded "
            f"the 30-minute safety timeout."
        ) from exc


    if result.returncode != 0:

        if os.path.isfile(temp_output_path):
            os.remove(temp_output_path)

        raise RuntimeError(
            f"Frame {frame}: VTK export failed:\n\n"
            f"{result.stderr}"
        )


    if "VALID" not in result.stdout:

        if os.path.isfile(temp_output_path):
            os.remove(temp_output_path)

        raise RuntimeError(
            f"Frame {frame}: VTK writer returned "
            f"unexpected output:\n\n"
            f"{result.stdout}"
        )


# ============================================================
# Verify temporary artifact
# ============================================================

if not os.path.isfile(temp_output_path):
    raise RuntimeError(
        f"Frame {frame}: temporary VTI was not created:\n"
        f"{temp_output_path}"
    )


temp_size = os.path.getsize(
    temp_output_path
)

if temp_size <= 0:

    os.remove(
        temp_output_path
    )

    raise RuntimeError(
        f"Frame {frame}: temporary VTI is empty:\n"
        f"{temp_output_path}"
    )


# ============================================================
# Publish artifact atomically
#
# A final *.vti exists only after the complete export and
# in-memory validation have succeeded.
# ============================================================

try:
    os.replace(
        temp_output_path,
        output_path,
    )

except Exception as exc:

    if os.path.isfile(temp_output_path):
        os.remove(temp_output_path)

    raise RuntimeError(
        f"Frame {frame}: failed to publish final VTI:\n"
        f"{output_path}\n\n"
        f"{exc}"
    ) from exc


# ============================================================
# Final lightweight filesystem check
# ============================================================

if not os.path.isfile(output_path):
    raise RuntimeError(
        f"Frame {frame}: final VTI is missing after publish:\n"
        f"{output_path}"
    )


if os.path.getsize(output_path) <= 0:
    raise RuntimeError(
        f"Frame {frame}: final VTI is empty:\n"
        f"{output_path}"
    )


# ============================================================
# Register validated artifact with PDG
# ============================================================

work_item.addOutputFile(
    output_path
)