"""Generate a TELEMAC-2D steering (``.cas``) file for a refinement case.

The steering file wires the generated mesh, boundary conditions, liquid
boundary time series, and requested output variables together with the
time discretisation and bottom-friction settings carried over from the
screening configuration.  A user-supplied template can be provided; in that
case only the path/run-control keywords are substituted so experts keep full
control of the physics keywords.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VARIABLES = ["ELEVATION Z", "VELOCITY U", "VELOCITY V"]

# TELEMAC v7 uses full variable names; v8 (the pinned public images) selects
# output variables by mnemonic (S=free surface, U/V=velocities, H=depth, B=bed).
_V7_TO_V8_MNEMONIC = {
    "ELEVATION Z": "S",
    "FREE SURFACE": "S",
    "ELEVATION": "S",
    "VELOCITY U": "U",
    "VELOCITY UX": "U",
    "VELOCITY V": "V",
    "VELOCITY VY": "V",
    "WATER DEPTH": "H",
    "DEPTH": "H",
    "BOTTOM": "B",
}


def _fmt_scalar(value) -> str:
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)
    return str(value)


def _fmt_list(values: list[str]) -> str:
    return ",".join(f"'{v}'" for v in values)


def _v8_variables(variables: list[str]) -> str:
    """Map full variable names to the v8 mnemonic list ('U,V,S')."""
    mnemonics = [_V7_TO_V8_MNEMONIC.get(v, v) for v in variables]
    return ",".join(dict.fromkeys(mnemonics))  # de-dup, keep order


def build_steering(
    cas_dir: str,
    time_step: float,
    n_steps: int,
    config: dict,
    *,
    title: str = "TIDAL-OSS TELEMAC REFINEMENT",
    variables: list[str] | None = None,
) -> str:
    """Write ``case.cas`` and return its path."""
    cas = Path(cas_dir)
    steering_cfg = config.get("steering", {}) if isinstance(config, dict) else {}

    template = steering_cfg.get("template")
    geom_file = "mesh.slf"
    bnd_file = "mesh.cli"
    liq_file = "mesh.liq"
    res_file = "r2d.slf"
    var_list = variables or steering_cfg.get("variables", DEFAULT_VARIABLES)

    base = {
        "TITLE": f"'{title}'",
        "GEOMETRY FILE": geom_file,
        "BOUNDARY CONDITIONS FILE": bnd_file,
        "LIQUID BOUNDARIES FILE": liq_file,
        "RESULTS FILE": res_file,
        "TIME STEP": _fmt_scalar(time_step),
        "NUMBER OF TIME STEPS": _fmt_scalar(int(n_steps)),
        "INITIAL TIME SET TO ZERO": "YES",
        "VARIABLES FOR GRAPHIC PRINTOUTS": f"'{_v8_variables(var_list)}'",
    }

    if template:
        txt = Path(template).read_text()
        subs = {
            "{{GEOMETRY}}": geom_file,
            "{{BOUNDARY}}": bnd_file,
            "{{LIQUID}}": liq_file,
            "{{RESULTS}}": res_file,
            "{{TIME_STEP}}": _fmt_scalar(time_step),
            "{{NSTEPS}}": _fmt_scalar(int(n_steps)),
            "{{VARIABLES}}": _fmt_list(var_list),
        }
        for key, val in subs.items():
            txt = txt.replace(key, val)
        out_path = cas / "case.cas"
        out_path.write_text(txt)
        return str(out_path)

    lines = ["/" + title, "/"]
    for key, val in base.items():
        lines.append(f"{key} : {val}")

    friction_law = steering_cfg.get("friction_law", 2)
    lines.append(f"LAW OF BOTTOM FRICTION : {_fmt_scalar(friction_law)}")
    if steering_cfg.get("linear_friction_coefficient") is not None:
        lines.append(
            "FRICTION COEFFICIENT : "
            f"{_fmt_scalar(steering_cfg['linear_friction_coefficient'])}"
        )
    elif steering_cfg.get("friction_coefficient") is not None:
        lines.append(
            f"FRICTION COEFFICIENT : {_fmt_scalar(steering_cfg['friction_coefficient'])}"
        )

    lines.extend(
        [
            "SOLVER : 1",
            "SOLVER ACCURACY : 1.0E-4",
            "MAXIMUM NUMBER OF ITERATIONS FOR SOLVER : 100",
            "FREE SURFACE GRADIENT COMPATIBILITY : 0.1",
            "MASS-LUMPING ON H : 1.0",
        ]
    )

    advection = steering_cfg.get("advection", False)
    lines.append("ADVECTION : YES" if advection else "ADVECTION : NO")

    out_path = cas / "case.cas"
    out_path.write_text("\n".join(lines) + "\n")
    return str(out_path)
