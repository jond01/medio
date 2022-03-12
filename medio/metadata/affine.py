from typing import Optional, Tuple, Union, TYPE_CHECKING

import numpy as np
from numpy.typing import ArrayLike, NDArray

_IndexType = Union[int, slice, ellipsis]
_ItemType2D = Tuple[_IndexType, _IndexType]
NDArrayFloat = NDArray[np.float64]

# if TYPE_CHECKING:
#     import sys
#
#     if sys.version_info.major < 3:
#         raise ValueError("Python 2 is not supported.")
#
#     if sys.version_info.minor < 8:
#         NDArrayFloat = NDArray[float]
#     else:
#         NDArrayFloat = NDArray[np.float_]
# else:
#     NDArrayFloat = np.ndarray

NDArrayFloat = NDArray[float]
_IndexType = Union[int, slice, ellipsis]
_ItemType2D = Tuple[_IndexType, _IndexType]


class Affine(NDArray[float]):
    """
    Class for general (d+1)x(d+1) affine matrices, and in particular d=3 (3d space)
    Usage examples:
    >>> affine1 = Affine(np.eye(4))
    >>> affine2 = Affine(direction=np.eye(3), spacing=[0.33, 1, 0.33], origin=[-90.3, 10, 1.44])
    >>> index = [4, 0, 9]
    >>> coord = affine2.index2coord(index)
    >>> print(coord)
    [-88.98  10.     4.41]
    """

    # keys for the origin and M matrix parts in the affine matrix
    _origin_key = (slice(-1), -1)
    _m_key = (slice(-1), slice(-1))

    def __new__(
        cls,
        affine: Optional[ArrayLike] = None,
        *,
        direction: Optional[ArrayLike] = None,
        spacing: Optional[ArrayLike] = None,
        origin: Optional[ArrayLike] = None,
    ) -> "Affine":
        """
        Construct a numpy array of class Affine. Initialize Affine in one of the following ways:
        1. (d+1)x(d+1) matrix as affine (d is the dimension of the space)
        2. affine=None and construction from direction, spacing and origin parameters
        :param affine: (d+1)x(d+1) affine matrix, comprised of the M matrix and origin shift b: y = M*x + b
        x is the index vector of length d and y is the corresponding physical coordinates vector of the same length
        :param direction: dxd direction matrix (only rotations without scaling)
        :param spacing: scaling of the axes - vector of length d
        :param origin: the origin - b in the formula above - vector of length d (or a scalar)
        :return: numpy.ndarray viewed as type 'Affine'
        """
        if affine is None:
            affine = cls.construct_affine(direction, spacing, origin)
        obj = np.asarray(affine).view(cls)  # return array view of type Affine
        return obj

    def __init__(
        self,
        affine: Optional[ArrayLike] = None,
        *,
        direction: Optional[ArrayLike] = None,
        spacing: Optional[ArrayLike] = None,
        origin: Optional[ArrayLike] = None,
    ):
        self.dim = self.shape[0] - 1
        if affine is None:
            self._spacing = np.asarray(spacing)
            self._direction = np.asarray(direction)
        else:
            # TODO: reconsider calculating it here
            self._spacing = self.affine2spacing(self)
            self._direction = self.affine2direction(self, self.spacing)

    def index2coord(self, index_vector: ArrayLike) -> np.ndarray:
        """Return y according to y = M*x + b"""
        return self._m_matrix @ index_vector + self.origin

    def __matmul__(self, other: ArrayLike) -> np.ndarray:
        return super().__matmul__(other).view(np.ndarray)

    def __getitem__(self, item: _ItemType2D) -> np.ndarray:
        return super().__getitem__(item).view(np.ndarray)

    def clone(self) -> "Affine":
        return Affine(self.copy())

    # Affine properties in addition to the numpy array
    @property
    def origin(self) -> NDArrayFloat:
        return self[self._origin_key]

    @origin.setter
    def origin(self, value: ArrayLike) -> None:
        self[self._origin_key] = value

    @property
    def spacing(self) -> np.ndarray:
        return self._spacing

    @spacing.setter
    def spacing(self, value: ArrayLike) -> None:
        value = np.asarray(value)
        self._m_matrix = self._m_matrix @ np.diag(value / self._spacing)
        # the spacing must be positive (or at least nonnegative)
        self._spacing = np.abs(value)

    @property
    def direction(self) -> np.ndarray:
        return self._direction

    @direction.setter
    def direction(self, value: ArrayLike) -> None:
        value = np.asarray(value)
        self._m_matrix = value @ np.diag(self.spacing)
        self._direction = value

    # Internal property - m matrix
    @property
    def _m_matrix(self) -> NDArrayFloat:
        return self[self._m_key]

    @_m_matrix.setter
    def _m_matrix(self, value: NDArrayFloat) -> None:
        self[self._m_key] = value

    # Static methods for affine construction and components
    @staticmethod
    def construct_affine(
        direction: ArrayLike, spacing: ArrayLike, origin: ArrayLike
    ) -> np.ndarray:
        direction = np.asarray(direction)
        dim = direction.shape[0]
        affine = np.eye(dim + 1)
        affine[Affine._m_key] = direction @ np.diag(spacing)
        affine[Affine._origin_key] = origin
        return affine

    @staticmethod
    def affine2origin(affine: NDArrayFloat) -> ArrayLike:
        return affine[Affine._origin_key]

    @staticmethod
    def affine2spacing(affine: NDArrayFloat) -> NDArrayFloat:
        dim = affine.shape[0] - 1
        return np.linalg.norm(affine[Affine._m_key] @ np.eye(dim), axis=0)

    @staticmethod
    def affine2direction(
        affine: NDArrayFloat, spacing: Optional[np.ndarray] = None
    ) -> NDArrayFloat:
        if spacing is None:
            spacing = Affine.affine2spacing(affine)
        return affine[Affine._m_key] @ np.diag(1 / spacing)

    @staticmethod
    def affine2comps(
        affine: NDArrayFloat, spacing: Optional[np.ndarray] = None
    ) -> Tuple[NDArrayFloat, NDArrayFloat, NDArrayFloat]:
        if spacing is None:
            spacing = Affine.affine2spacing(affine)
        return (
            Affine.affine2direction(affine, spacing),
            spacing,
            Affine.affine2origin(affine),
        )
