"""
NiBabel <-> ITK orientation and affine conversion utilities.
The conventions of nibabel and itk are different and this module supplies functions
which convert between these conventions.

Orientation
-----------
In nibabel each axis code indicates the ending direction - RAS+: L -> R, P -> A, I -> S
In itk it corresponds to the converse of nibabel - RAS: R -> L, A -> P, S -> I

Affine
------
In itk, the direction matrix (3x3 upper left affine with unit spacings) of RAS
orientation image is:
[[1, 0, 0],
 [0, 1, 0],
 [0, 0, -1]]

In nibabel it is LPI+:
[[-1, 0, 0],
 [0, -1, 0],
 [0, 0, -1]]

The matrix convert_aff_mat accounts for this difference (for all possible orientations,
not only RAS).

Usage
=====
Works both ways: itk -> nib and nib -> itk, the usage is the same:
>>> new_affine, new_axcodes = convert_nib_itk(affine, axcodes)
"""

from typing import Iterable, Optional, Union, Tuple, overload, List

import numpy as np

from medio.metadata.affine import Affine
from medio.utils.two_way_dict import TwoWayDict

# store compactly axis directions codes
AXES_INV: TwoWayDict[str] = TwoWayDict()
AXES_INV["R"] = "L"
AXES_INV["A"] = "P"
AXES_INV["S"] = "I"

CONVERT_AFF_MAT4 = np.diag([-1, -1, 1, 1])
CONVERT_AFF_MAT3 = np.diag([-1, -1, 1])


@overload
def inv_axcodes(axcodes: Iterable[str]) -> str:
    ...


@overload
def inv_axcodes(axcodes: None) -> None:
    ...


def inv_axcodes(axcodes: Optional[Iterable[str]]) -> Optional[str]:
    """Inverse axes codes chars, for example: SPL -> IAR"""
    if axcodes is None:
        return None
    new_axcodes = ""
    for code in axcodes:
        new_axcodes += AXES_INV[code]
    return new_axcodes


@overload
def convert_affine(affine: Affine) -> Affine:
    ...


@overload
def convert_affine(affine: np.ndarray) -> np.ndarray:
    ...


def convert_affine(affine: Union[Affine, np.ndarray]) -> Union[Affine, np.ndarray]:
    # conversion matrix of the affine from itk to nibabel and vice versa
    convert_aff_mat = CONVERT_AFF_MAT4
    # for 2d image:
    if affine.shape[0] == 3:
        convert_aff_mat = CONVERT_AFF_MAT3
    new_affine = convert_aff_mat @ affine
    if isinstance(affine, Affine):
        new_affine = Affine(new_affine)
    return new_affine


@overload
def convert_nib_itk(
    affine: Affine,
    axcodes: Iterable[Optional[Iterable[str]]],
) -> Tuple[Affine, List[Optional[str]]]:
    ...


@overload
def convert_nib_itk(
    affine: np.ndarray,
    axcodes: Iterable[Optional[Iterable[str]]],
) -> Tuple[np.ndarray, List[Optional[str]]]:
    ...


def convert_nib_itk(
    affine: Union[Affine, np.ndarray],
    axcodes: Iterable[Optional[Iterable[str]]],
) -> Tuple[Union[Affine, np.ndarray], List[Optional[str]]]:
    """
    Convert affine and orientations (original and current orientations) from nibabel to
    itk and vice versa
    """
    new_affine = convert_affine(affine)
    new_axcodes = [inv_axcodes(axcode) for axcode in axcodes]
    return new_affine, new_axcodes
