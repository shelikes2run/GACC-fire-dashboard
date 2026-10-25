// Area settings for this copy of the site. The setup notebook (setup_area.ipynb) writes this file;
// the pages and the build scripts (site/area.py) both read it. Keep it valid JSON inside the braces.
window.AREA = {
  "id": "CA",
  "name": "California",
  "title": "California Fire Danger Rating Areas",
  "short_title": "CA FDRA Fire Danger",
  "subtitle": "CA GACC Predictive Services · National Forest FDRAs · NFDRS 2016 fuel models",
  "org": "CA GACC Predictive Services",
  "repo": "shelikes2run/GACC-fire-dashboard",
  "states": ["CA", "HI", "GU", "AS", "MP"],
  "bounds": [[32.4, -124.6], [42.1, -114.0]],
  "timezone": "America/Los_Angeles",
  "crs": 3310,
  "stations_source": "ca_nfdrs",
  "perimeters": "frap",
  "pal": {"enabled": true, "matrix": "R5", "label": "CA PAL Combined Report",
          "url": "https://gacc.nifc.gov/oscc/predictive/weather/pal_combined_report.html"},
  "raws_layer": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/PublicView_RAWS/FeatureServer/1"
};
