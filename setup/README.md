# Setting up the site for another area

This repository is a template. To build the FDRA fire danger site for your own area:

1. On GitHub, click **Use this template → Create a new repository**. Make the new repository **public**.
2. Open the new repository in **GitHub Codespaces** (green **Code** button → **Codespaces** → **Create codespace on main**).
3. Open `setup/setup_area.ipynb`, pick the **Python 3** kernel, and run the cells top to bottom. The notebook walks you through:
   - your area settings (name, states, time zone);
   - your FDRA boundaries (shapefiles, GeoJSON or a file geodatabase in `setup/inputs/`);
   - each FDRA's SIG stations, checked against the national RAWS list and FEMS;
   - the thresholds workbook, `site/thresholds/FDRA_thresholds.xlsx`;
   - publishing (git push), and turning on GitHub Pages;
   - optionally, an ArcGIS Online layer and web map, with your own sign-in.
4. In the repository **Settings → Pages**, publish from **main / docs**.

No codespace? Edit the settings cells of the notebook in GitHub, then run **Actions → Run setup notebook**. The executed notebook, with every check's output, is saved as `setup/setup_area.out.ipynb`.

`setup/examples/noco/` is a worked example: the Northern Colorado 2026 FDOP, with five FDRAs, ERC × BI matrices, Tmax / 100-hr / GSI adjustments and 4-day averages. With `EXAMPLE = 'noco'` the notebook builds the whole NoCo site from it.

No keys or passwords are needed for the site itself. FEMS, the RAWS layer and the fire history sources are all public.
