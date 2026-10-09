"""
GridPulse — Scientific Thermal & Aging Solvers
Part of scientific.thermal.

Implements verified, standard-specific differential thermal state solvers
and insulation aging degradation equations for:
1. IEEE Std C57.91-2011 (Annex G & Clause 5).
2. IEC 60076-7:2018 (Clause 7 & Clause 6).

SCIENTIFIC CONTRACT RULES:
- Reconciled IEEE K^(2y) and IEC K^y exponents.
- Exponential recurrence requires an established prior state; never manufactures initial conditions.
- Zero arbitrary Arrhenius clamping; safe numerical domain validation.
- Emits ERR_UNSAFE_ARRHENIUS_EVALUATION on domain or overflow failures.
"""

from datetime import datetime
import math
from typing import Optional, Tuple

from scientific.contracts.enums import (
    InsulationSystemType,
    IssueSeverity,
    ThermalModelStandard,
)
from scientific.contracts.issues import (
    ERR_UNSAFE_ARRHENIUS_EVALUATION,
    ProcessingIssue,
)


# ==============================================================================
# Reference Hot-Spot Temperatures (°C)
# ==============================================================================

IEEE_REF_TEMP_UPGRADED_C = 110.0       # IEEE C57.91 120°C insulation class (65°C rise)
IEEE_REF_TEMP_NON_UPGRADED_C = 95.0    # IEEE C57.91 105°C insulation class (55°C rise)

IEC_REF_TEMP_UPGRADED_C = 110.0        # IEC 60076-7 thermally upgraded paper
IEC_REF_TEMP_NON_UPGRADED_C = 98.0     # IEC 60076-7 non-thermally upgraded paper

ARRHENIUS_ACTIVATION_CONSTANT_B = 15000.0  # Activation energy constant (Kelvin)
KELVIN_OFFSET = 273.15


# ==============================================================================
# Standard-Specific Thermal Rise Formulations
# ==============================================================================

def calculate_ieee_ultimate_top_oil_rise(
    loading_pu: float,
    rated_top_oil_rise_k: float,
    loss_ratio_r: float,
    oil_exponent_x: float,
) -> float:
    """
    IEEE Std C57.91-2011 ultimate top-oil temperature rise over ambient.
    delta_theta_oil,u = delta_theta_oil,rated * ((K^2 * R + 1) / (R + 1))^x
    """
    k = max(0.0, float(loading_pu))
    r = float(loss_ratio_r)
    loss_factor = (k * k * r + 1.0) / (r + 1.0)
    return float(rated_top_oil_rise_k) * (loss_factor ** float(oil_exponent_x))


def calculate_ieee_ultimate_hot_spot_rise(
    loading_pu: float,
    rated_hot_spot_rise_k: float,
    winding_exponent_y: float,
) -> float:
    """
    IEEE Std C57.91-2011 ultimate hot-spot temperature rise over top oil.
    delta_theta_hs,u = delta_theta_hs,rated * K^(2 * y_ieee)
    """
    k = max(0.0, float(loading_pu))
    if k == 0.0:
        return 0.0
    exponent = 2.0 * float(winding_exponent_y)
    return float(rated_hot_spot_rise_k) * (k ** exponent)


def calculate_iec_ultimate_top_oil_rise(
    loading_pu: float,
    rated_top_oil_rise_k: float,
    loss_ratio_r: float,
    oil_exponent_x: float,
) -> float:
    """
    IEC 60076-7:2018 ultimate top-oil temperature rise over ambient.
    delta_theta_oil,u = delta_theta_oil,rated * ((1 + K^2 * R) / (1 + R))^x
    """
    k = max(0.0, float(loading_pu))
    r = float(loss_ratio_r)
    loss_factor = (1.0 + k * k * r) / (1.0 + r)
    return float(rated_top_oil_rise_k) * (loss_factor ** float(oil_exponent_x))


def calculate_iec_ultimate_hot_spot_rise(
    loading_pu: float,
    rated_hot_spot_rise_k: float,
    winding_exponent_y: float,
) -> float:
    """
    IEC 60076-7:2018 ultimate hot-spot temperature rise over top oil.
    delta_theta_hs,u = (H * g_rated) * K^(y_iec) = delta_theta_hs,rated * K^(y_iec)
    Note: In IEC, exponent y_iec is applied directly to current ratio K.
    """
    k = max(0.0, float(loading_pu))
    if k == 0.0:
        return 0.0
    return float(rated_hot_spot_rise_k) * (k ** float(winding_exponent_y))


def solve_exponential_recurrence(
    prior_rise_k: float,
    ultimate_rise_k: float,
    duration_hours: float,
    time_constant_hours: float,
) -> float:
    """
    Exact analytical solution to the first-order linear thermal differential equation
    under piecewise constant loading over interval delta_t:
    delta_theta(t + dt) = delta_theta(t) * exp(-dt / tau) + delta_theta_u * (1 - exp(-dt / tau))
    """
    if duration_hours < 0.0:
        raise ValueError(f"duration_hours must be non-negative (got {duration_hours}).")
    if time_constant_hours <= 0.0:
        raise ValueError(f"time_constant_hours must be strictly positive (got {time_constant_hours}).")
    if duration_hours == 0.0:
        return float(prior_rise_k)

    decay = math.exp(-duration_hours / time_constant_hours)
    return float(prior_rise_k) * decay + float(ultimate_rise_k) * (1.0 - decay)


# ==============================================================================
# Aging Rate & Degradation Kinetics
# ==============================================================================

def calculate_ieee_aging_acceleration_factor(
    hot_spot_temp_c: float,
    insulation_system: InsulationSystemType,
    stage: str = "thermal_aging_solver",
) -> Tuple[Optional[float], Optional[ProcessingIssue], float]:
    """
    Evaluates IEEE Std C57.91-2011 Aging Acceleration Factor (F_AA).
    F_AA = exp(15000 / (T_ref + 273.15) - 15000 / (theta_hs + 273.15))

    Returns:
        (f_aa, issue, ref_temp_c)
        If calculation violates thermodynamics or causes numerical overflow,
        returns (None, ProcessingIssue, ref_temp_c).
    """
    if insulation_system == InsulationSystemType.THERMALLY_UPGRADED_PAPER:
        t_ref_c = IEEE_REF_TEMP_UPGRADED_C
    else:
        t_ref_c = IEEE_REF_TEMP_NON_UPGRADED_C

    # Validate finite float input
    if math.isnan(hot_spot_temp_c) or math.isinf(hot_spot_temp_c):
        return None, ProcessingIssue(
            stage=stage,
            severity=IssueSeverity.CRITICAL,
            code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
            message=f"Non-finite hot-spot temperature ({hot_spot_temp_c}°C) encountered.",
            field_name="hot_spot_temp_c",
        ), t_ref_c

    # Absolute zero violation guard
    t_abs_k = hot_spot_temp_c + KELVIN_OFFSET
    if t_abs_k <= 0.0:
        return None, ProcessingIssue(
            stage=stage,
            severity=IssueSeverity.CRITICAL,
            code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
            message=(
                f"Hot-spot temperature {hot_spot_temp_c}°C violates absolute zero "
                f"({t_abs_k:.2f} K <= 0 K). Thermodynamic violation."
            ),
            field_name="hot_spot_temp_c",
        ), t_ref_c

    t_ref_k = t_ref_c + KELVIN_OFFSET
    exponent = (ARRHENIUS_ACTIVATION_CONSTANT_B / t_ref_k) - (ARRHENIUS_ACTIVATION_CONSTANT_B / t_abs_k)

    # Float overflow guard (IEEE 754 max exp is ~709.78)
    if exponent >= 700.0:
        return None, ProcessingIssue(
            stage=stage,
            severity=IssueSeverity.CRITICAL,
            code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
            message=(
                f"Arrhenius exponent {exponent:.2f} at hot-spot temperature {hot_spot_temp_c}°C "
                f"would cause numerical float overflow."
            ),
            field_name="aging_acceleration_factor_faa",
        ), t_ref_c

    # Underflow check: extremely low temperatures yield degradation ~0.0
    if exponent <= -700.0:
        return 0.0, None, t_ref_c

    return math.exp(exponent), None, t_ref_c


def calculate_iec_relative_ageing_rate(
    hot_spot_temp_c: float,
    insulation_system: InsulationSystemType,
    stage: str = "thermal_aging_solver",
) -> Tuple[Optional[float], Optional[ProcessingIssue], float]:
    """
    Evaluates IEC 60076-7:2018 Relative Ageing Rate (V).
    For non-upgraded paper:
        V = 2^((theta_hs - 98.0) / 6.0)
    For thermally upgraded paper:
        V = exp(15000 / (110.0 + 273.15) - 15000 / (theta_hs + 273.15))

    Returns:
        (v, issue, ref_temp_c)
    """
    if insulation_system == InsulationSystemType.THERMALLY_UPGRADED_PAPER:
        t_ref_c = IEC_REF_TEMP_UPGRADED_C

        if math.isnan(hot_spot_temp_c) or math.isinf(hot_spot_temp_c):
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=f"Non-finite hot-spot temperature ({hot_spot_temp_c}°C) encountered.",
                field_name="hot_spot_temp_c",
            ), t_ref_c

        t_abs_k = hot_spot_temp_c + KELVIN_OFFSET
        if t_abs_k <= 0.0:
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=(
                    f"Hot-spot temperature {hot_spot_temp_c}°C violates absolute zero "
                    f"({t_abs_k:.2f} K <= 0 K). Thermodynamic violation."
                ),
                field_name="hot_spot_temp_c",
            ), t_ref_c

        t_ref_k = t_ref_c + KELVIN_OFFSET
        exponent = (ARRHENIUS_ACTIVATION_CONSTANT_B / t_ref_k) - (ARRHENIUS_ACTIVATION_CONSTANT_B / t_abs_k)

        if exponent >= 700.0:
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=(
                    f"Arrhenius exponent {exponent:.2f} at hot-spot temperature {hot_spot_temp_c}°C "
                    f"would cause numerical float overflow."
                ),
                field_name="relative_ageing_rate_v",
            ), t_ref_c

        if exponent <= -700.0:
            return 0.0, None, t_ref_c

        return math.exp(exponent), None, t_ref_c

    else:
        # Non-thermally upgraded paper: IEC 2^((theta_hs - 98) / 6)
        t_ref_c = IEC_REF_TEMP_NON_UPGRADED_C

        if math.isnan(hot_spot_temp_c) or math.isinf(hot_spot_temp_c):
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=f"Non-finite hot-spot temperature ({hot_spot_temp_c}°C) encountered.",
                field_name="hot_spot_temp_c",
            ), t_ref_c

        # Absolute zero check
        if hot_spot_temp_c + KELVIN_OFFSET <= 0.0:
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=f"Hot-spot temperature {hot_spot_temp_c}°C violates absolute zero.",
                field_name="hot_spot_temp_c",
            ), t_ref_c

        power = (hot_spot_temp_c - t_ref_c) / 6.0

        # Float overflow guard (2^1020 is near max float)
        if power >= 1020.0:
            return None, ProcessingIssue(
                stage=stage,
                severity=IssueSeverity.CRITICAL,
                code=ERR_UNSAFE_ARRHENIUS_EVALUATION,
                message=(
                    f"IEC aging power 2^{power:.2f} at hot-spot temperature {hot_spot_temp_c}°C "
                    f"would cause numerical float overflow."
                ),
                field_name="relative_ageing_rate_v",
            ), t_ref_c

        if power <= -1020.0:
            return 0.0, None, t_ref_c

        return 2.0 ** power, None, t_ref_c
