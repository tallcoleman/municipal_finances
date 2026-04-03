# Municipal Boundary Files

Source: https://data.ontario.ca/dataset/municipal-boundaries

Contains two datasets:

- [lower and single tier municipalities](https://data.ontario.ca/dataset/municipal-boundaries/resource/82ce5025-bb37-43bd-8791-2a5eebed329a)
- [upper tier municipalities and districts](https://data.ontario.ca/dataset/municipal-boundaries/resource/b34767bc-7d6c-4c97-b9ce-7f573b0937c9)

Formats:

- Was able to download both in CSV format, but CSV files do not have geometry.
- Had trouble downloading the upper tier data in GeoJSON; was only able to download lower tier in this format. File is too big for regular git storage, so converted the GeoJSON file to parquet (see script below).
- Was also unable to download unzip bundle for upper tier in Shapefile format (but did not save any Shapefiles since GeoJSON is preferred).

Parquet conversion:

```py
import geopandas as gpd

boundary = gpd.read_file("path_to_input_file.geojson")
boundary.to_parquet("path_to_output_file.parquet")
```