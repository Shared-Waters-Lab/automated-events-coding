"""Point -> basin code, using the existing basin polygons."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

_EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class BasinLocator:
    """Find which basin polygon(s) contain a point.

    snap_km is off by default. If set, a point that falls in no polygon is
    assigned to the nearest basin within that distance. It exists for river
    mouths that sit on a generalized coastline; it is a property of how
    detailed the shapefile is, not something to tune for accuracy.
    """

    def __init__(
        self,
        geometries: Sequence[BaseGeometry],
        codes: Sequence[str],
        *,
        snap_km: float | None = None,
    ):
        if len(geometries) != len(codes):
            raise ValueError("geometries and codes must have the same length")
        self._geoms = [shapely.make_valid(g) for g in geometries]
        self._codes = [str(c) for c in codes]
        self._tree = shapely.STRtree(self._geoms)
        self._snap_km = snap_km

    @classmethod
    def from_file(
        cls, path: str | Path, code_field: str = "BCODE", *, snap_km: float | None = None
    ) -> BasinLocator:
        import geopandas as gpd

        gdf = gpd.read_file(path)
        if code_field not in gdf.columns:
            raise KeyError(f"{path}: no {code_field!r} column (have {list(gdf.columns)})")
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)
        gdf = gdf[gdf[code_field].notna() & gdf.geometry.notna()]
        return cls(list(gdf.geometry), list(gdf[code_field]), snap_km=snap_km)

    def basins_at(self, *, lat: float, lon: float) -> frozenset[str]:
        point = Point(lon, lat)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits):
            return frozenset(self._codes[i] for i in hits)
        if not self._snap_km:
            return frozenset()

        # Search radius in degrees, generous at high latitudes; the exact
        # distance is then checked with haversine.
        deg = self._snap_km / 111.32 / max(math.cos(math.radians(lat)), 0.01)
        idx = self._tree.query_nearest(point, max_distance=deg, all_matches=True)
        out = set()
        for i in idx:
            near = nearest_points(point, self._geoms[i])[1]
            if _haversine_km(lat, lon, near.y, near.x) <= self._snap_km:
                out.add(self._codes[i])
        return frozenset(out)