# FDRA thresholds

`FDRA_thresholds.xlsx` holds every FDRA's FDOP decision thresholds: staffing, adjective, dispatch and any other tools, plus the plan details (SIG stations, season, calibration years, large-fire size). The site popups, the Today box, the AGOL popups and the FDOP Workbench all start from it.

**To update it:**

1. Click `FDRA_thresholds.xlsx` above, then **Download raw file**.
2. Edit it in Excel. The **How to update** sheet inside explains each column.
3. Come back to this folder and choose **Add file → Upload files**. Drop the file in, write a short note (for example "LPF 2027 FDOP"), and choose **Commit changes**.
4. Watch the **Actions** tab. A green check under **Thresholds check** means the file is good. A red X lists each problem by sheet and row (GitHub also emails you). Fix those rows and upload again. FDRAs with problems keep their last good thresholds; everything else updates.
5. The site build starts on its own, and the new thresholds are live in about 15–30 minutes.

Breakpoints are the **top** of their class: a value above Break 1 is in class 2.
