from typing import TypeVar, Dict

_T = TypeVar("_T")  # the key and value types are the same in two-way dict


class TwoWayDict(Dict[_T, _T]):
    """Dictionary that contains key-value + value-key pairs: {key: value, value: key}"""

    def __setitem__(self, key: _T, value: _T) -> None:
        # Remove any previous connections with these values
        if key in self:
            del self[key]
        if value in self:
            del self[value]
        dict.__setitem__(self, key, value)
        dict.__setitem__(self, value, key)

    def __delitem__(self, key: _T) -> None:
        dict.__delitem__(self, self[key])
        dict.__delitem__(self, key)

    def __len__(self) -> int:
        """Returns the number of connections"""
        return dict.__len__(self) // 2
