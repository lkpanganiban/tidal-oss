"""Read/write TELEMAC Selafin (SERAFIN) mesh and result files.

The SERAFIN format is a sequence of length-tagged binary records (Fortran
sequential-unformatted layout): every record is ``<int32 n> <data> <int32 n>``.
TELEMAC v7/v8 (the public Docker images pinned by this repository) use a
*binary* header where the scalar header fields (number of variables, IPARAM,
mesh dimensions) are stored as raw ``int32`` records.  Legacy v5/v6 files use
an ASCII variant where those same fields are ``I5`` text records of fixed
length.  This module writes the modern binary layout and reads both, with
automatic endianness detection.

Header layout produced (all integers ``int32``, floats ``float32``)::

    TITLE   : 80-byte record (72-char title + 8-char magic "SERAFIN ")
    NVAR    : 8-byte record  (nvar, 0)
    VARINFO : 32-byte record per variable (16-char name + 16-char unit)
    IPARAM  : 40-byte record (10 int32; [7]=nplan, [8]=nptfr, [9]=nptir)
    DIM     : 16-byte record (nelem, npoin, ndp, 1)
    IKLE    : nelem*ndp int32 (1-based connectivity)
    IPOBO   : npoin int32 (0 = interior; k = k-th boundary point)
    X / Y   : npoin float32
    VALUES  : npoin float32 per variable (geometry files only)

Result files repeat ``<time float32> <var1 npoin float32> ...`` after the
header.  Only the single-precision ``SERAFIN `` variant is produced.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

SERAFIN_MAGIC = b"SERAFIN "
ENDIAN = "<"
_TITLE_SIZE = 80
_VAR_SIZE = 32


class SerafinError(Exception):
    """Raised on malformed Selafin files or unsupported options."""


@dataclass
class SerafinGeometry:
    """In-memory representation of a 2D TELEMAC mesh."""

    title: str
    x: np.ndarray
    y: np.ndarray
    ikle: np.ndarray
    var_names: list[str] = field(default_factory=lambda: ["ELEVATION Z"])
    var_units: list[str] = field(default_factory=lambda: ["M"])
    values: np.ndarray | None = None
    ipobo: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))
    nvb2: int = 0
    iparam: list[int] = field(default_factory=lambda: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    @property
    def npoin(self) -> int:
        return int(self.x.shape[0])

    @property
    def nelem(self) -> int:
        return int(self.ikle.shape[0])

    @property
    def ndp(self) -> int:
        return int(self.ikle.shape[1])


def _read_record(f, endian: str = ENDIAN) -> bytes:
    head = f.read(4)
    if len(head) < 4:
        raise EOFError("unexpected end of Selafin file")
    (n,) = struct.unpack(endian + "i", head)
    data = f.read(n)
    tail = f.read(4)
    if len(data) != n or len(tail) < 4:
        raise SerafinError("record length marker mismatch")
    return data


def _write_record(f, data: bytes) -> None:
    n = len(data)
    f.write(struct.pack(ENDIAN + "i", n))
    f.write(data)
    f.write(struct.pack(ENDIAN + "i", n))


def _pack_int5(value: int) -> bytes:
    return f"{int(value):5d}".encode("ascii")


def _detect_endian(path: str) -> str:
    """Detect byte order from the first (title) record length marker (== 80)."""
    with open(path, "rb") as f:
        head = f.read(4)
    if len(head) < 4:
        raise SerafinError("file too short to be SERAFIN")
    if struct.unpack("<i", head)[0] == _TITLE_SIZE:
        return "<"
    if struct.unpack(">i", head)[0] == _TITLE_SIZE:
        return ">"
    raise SerafinError("not a SERAFIN file (bad title record length)")


def compute_ipobo(ikle: np.ndarray, npoints: int | None = None) -> np.ndarray:
    """Return a 1-based boundary-point numbering array (0 = interior).

    The returned array has one entry per node (``ipobo[node - 1]`` is the
    boundary index of 1-based node ``node``) so its length is always
    ``npoints`` even when some nodes are unreferenced by ``ikle`` (orphan
    nodes), which would otherwise truncate the Serafin IPOBO record.
    """
    ikle = np.asarray(ikle)
    if npoints is None:
        npoints = int(ikle.max())
    ndp = ikle.shape[1]
    edges = []
    for k in range(ndp):
        a = ikle[:, k]
        b = ikle[:, (k + 1) % ndp]
        edges.append(np.stack([np.minimum(a, b), np.maximum(a, b)], axis=1))
    edges = np.concatenate(edges, axis=0)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    boundary_nodes = uniq[counts == 1]
    node_set = np.unique(boundary_nodes)
    ipobo = np.zeros(npoints, dtype=np.int64)
    order = np.sort(node_set)
    for i, node in enumerate(order, start=1):
        ipobo[node] = i
    return ipobo


def write_geometry(
    path: str,
    x: np.ndarray,
    y: np.ndarray,
    ikle: np.ndarray,
    *,
    title: str = "TIDAL-OSS REFINEMENT MESH",
    bed_elevation: np.ndarray | None = None,
    var_name: str = "ELEVATION Z",
    var_unit: str = "M",
) -> SerafinGeometry:
    """Write a 2D triangular geometry file in the v8 binary SERAFIN format.

    ``ikle`` is 0-based on input and stored 1-based on disk.  ``bed_elevation``
    is written as the first variable (``ELEVATION Z``).
    """
    x = np.asarray(x, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    ikle = np.asarray(ikle, dtype=np.int64)
    if ikle.shape[1] != 3:
        raise SerafinError("only triangular meshes (NDP=3) are supported")
    if bed_elevation is None:
        bed_elevation = np.zeros_like(x)
    bed_elevation = np.asarray(bed_elevation, dtype=np.float32)

    ipobo = compute_ipobo(ikle, x.shape[0])
    iparam = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    title_block = (
        (title[:72].ljust(72) + SERAFIN_MAGIC.decode())
        .encode("ascii")[:80]
        .ljust(80, b" ")
    )
    nvar_block = struct.pack(ENDIAN + "2i", 1, 0)
    name_block = (var_name[:16].ljust(16) + var_unit[:16].ljust(16)).encode("ascii")
    iparam_block = struct.pack(ENDIAN + "10i", *iparam)
    dim_block = struct.pack(ENDIAN + "4i", ikle.shape[0], x.shape[0], 3, 1)

    ikle_1 = (ikle + 1).astype(np.int32)
    ikle_bytes = ikle_1.ravel().tobytes()
    ipobo_bytes = ipobo.astype(np.int32).tobytes()
    x_bytes = x.astype(np.float32).tobytes()
    y_bytes = y.astype(np.float32).tobytes()
    bed_bytes = bed_elevation.astype(np.float32).tobytes()

    with open(path, "wb") as f:
        _write_record(f, title_block)
        _write_record(f, nvar_block)
        _write_record(f, name_block)
        _write_record(f, iparam_block)
        _write_record(f, dim_block)
        _write_record(f, ikle_bytes)
        _write_record(f, ipobo_bytes)
        _write_record(f, x_bytes)
        _write_record(f, y_bytes)
        _write_record(f, bed_bytes)

    return SerafinGeometry(
        title=title,
        x=x,
        y=y,
        ikle=ikle,
        var_names=[var_name],
        var_units=[var_unit],
        values=bed_elevation,
        ipobo=ipobo,
    )


def _read_mesh_arrays(f, header: dict, endian: str):
    """Read the ikle / ipobo / node-x / node-y records shared by both file types.

    Returns ``(ikle, ipobo, x, y)`` with ``ikle`` 0-based.  Result files stop
    here (time records follow); geometry files additionally carry the geometry
    variable records, which :func:`read_geometry` reads separately.
    """
    ndp = header["ndp"]
    ikle = (
        np.frombuffer(_read_record(f, endian), dtype=endian + "i4")
        .reshape(-1, ndp)
        .astype(np.int64)
        - 1
    )
    ipobo = np.frombuffer(_read_record(f, endian), dtype=endian + "i4").astype(np.int64)
    x = np.frombuffer(_read_record(f, endian), dtype=endian + "f4").astype(np.float64)
    y = np.frombuffer(_read_record(f, endian), dtype=endian + "f4").astype(np.float64)
    return ikle, ipobo, x, y


def read_geometry(path: str) -> SerafinGeometry:
    """Parse a TELEMAC geometry/mesh file (binary or legacy ASCII)."""
    header = _read_serafin_header(path)
    endian = header["endian"]
    with open(path, "rb") as f:
        f.seek(header["data_offset"])
        ikle, ipobo, x, y = _read_mesh_arrays(f, header, endian)
        values = None
        if header["nvb1"] >= 1:
            var_bytes = _read_record(f, endian)
            values = np.frombuffer(var_bytes, dtype=endian + "f4").astype(np.float64)
            for _ in range(header["nvb1"] - 1):
                _read_record(f, endian)
    return SerafinGeometry(
        title=header["title"],
        x=x,
        y=y,
        ikle=ikle,
        var_names=header["var_names"],
        var_units=header["var_units"],
        values=values,
        ipobo=ipobo,
        nvb2=header["nvb2"],
        iparam=header["iparam"],
    )


def _read_serafin_header(path: str) -> dict:
    endian = _detect_endian(path)
    with open(path, "rb") as f:
        title_block = _read_record(f, endian)
        if title_block[72:80] not in (SERAFIN_MAGIC, b"SERAFIND"):
            raise SerafinError("not a SERAFIN file (missing magic bytes)")
        title = title_block[:72].decode("ascii", "replace").strip()
        nvar_block = _read_record(f, endian)
        if len(nvar_block) == 8:
            # Modern binary header: two int32 (nvar, nplan/ndp).
            nvb1, nvb2 = struct.unpack(endian + "2i", nvar_block)
        else:
            # Legacy ASCII header: two I5 fields in an 80-byte record.
            nvb1 = int(nvar_block[0:5])
            nvb2 = int(nvar_block[5:10])
        var_names, var_units = [], []
        for _ in range(nvb1):
            rec = _read_record(f, endian)
            var_names.append(rec[:16].decode("ascii", "replace").strip())
            var_units.append(rec[16:32].decode("ascii", "replace").strip())
        iparam_block = _read_record(f, endian)
        if len(iparam_block) == 40:
            iparam = list(struct.unpack(endian + "10i", iparam_block))
        else:
            iparam = [int(iparam_block[i * 5 : i * 5 + 5]) for i in range(10)]
        # v8 writes a 6-integer date/time record after IPARAM when IB(10) != 0.
        if iparam[9] != 0:
            _read_record(f, endian)
        dim_block = _read_record(f, endian)
        if len(dim_block) == 16:
            nelem, npoin, ndp, _ = struct.unpack(endian + "4i", dim_block)
        else:
            nelem = int(dim_block[0:5])
            npoin = int(dim_block[5:10])
            ndp = int(dim_block[10:15])
        data_offset = f.tell()
    return {
        "title": title,
        "nvb1": nvb1,
        "nvb2": nvb2,
        "var_names": var_names,
        "var_units": var_units,
        "iparam": iparam,
        "nelem": nelem,
        "npoin": npoin,
        "ndp": ndp,
        "data_offset": data_offset,
        "endian": endian,
    }


def read_serafin(path: str) -> dict:
    """Read a TELEMAC result file into a dictionary.

    Returns a mapping with keys ``header`` (the header dict), ``times``
    (``np.ndarray`` of record times), ``node_x``/``node_y`` (coordinates), and
    ``variables`` (dict mapping variable name to a ``(nt, npoin)`` array).
    """
    header = _read_serafin_header(path)
    endian = header["endian"]
    npoin = header["npoin"]
    times: list[float] = []
    var_arrays: dict[str, list[np.ndarray]] = {name: [] for name in header["var_names"]}

    with open(path, "rb") as f:
        f.seek(header["data_offset"])
        ikle, _ipobo, x, y = _read_mesh_arrays(f, header, endian)

        while True:
            try:
                t_block = _read_record(f, endian)
            except (EOFError, SerafinError):
                break
            if len(t_block) < 4:
                break
            times.append(struct.unpack(endian + "f", t_block[:4])[0])
            for _name in header["var_names"]:
                rec = _read_record(f, endian)
                arr = np.frombuffer(rec, dtype=endian + "f4").astype(np.float64)
                if arr.shape[0] != npoin:
                    raise SerafinError("variable record length mismatch")
                var_arrays[_name].append(arr)

    variables = {name: np.asarray(v) for name, v in var_arrays.items() if v}
    times_arr = np.asarray(times, dtype=np.float64)
    return {
        "header": header,
        "times": times_arr,
        "node_x": x,
        "node_y": y,
        "ikle": ikle,
        "variables": variables,
    }
