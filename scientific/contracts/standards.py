"""
GridPulse — Engineering Standards Reference Representation
Part of scientific.contracts (Source of Truth)

Represents formal standards references associated with telemetry definitions,
thermal models, and electrical limits.

IMPORTANT SCIENTIFIC GOVERNANCE:
Citing a standard does NOT claim that an engineering calculation is validated
merely by reference. Actual engineering-method implementation and numerical
verification are executed and validated in later scientific pipeline steps.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StandardReference:
    """
    Formal reference to an engineering standard governing physical formulations,
    tolerances, or diagnostic limits.

    Attributes:
        standard_id: Standard organization and designation (e.g., 'IEEE C57.91', 'IEC 60076-7').
        edition_year: Publication or revision year (e.g., '2011', '2018').
        purpose_context: Specific scope or clause addressed by the reference.
        associated_target: Optional reference to an assumption, parameter, or future calculation method.
    """
    standard_id: str
    edition_year: str
    purpose_context: str
    associated_target: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.standard_id or not self.standard_id.strip():
            raise ValueError("standard_id must be a non-empty string.")
        if not self.edition_year or not self.edition_year.strip():
            raise ValueError("edition_year must be a non-empty string.")
        if not self.purpose_context or not self.purpose_context.strip():
            raise ValueError("purpose_context must be a non-empty string.")
