# Preview fit update

Removed the 200–320px desktop height cap. Each camera frame now grows vertically to its decoded image aspect ratio, preserving the full image with object-fit: contain. Missing frames keep existing geometry; ROI dragging freezes ratio updates.

Regression test failed before the change and passed afterward. Python: 15 tests. Node: 11 suites. Mocked Chromium navigation and populated previews: 375/768/1024/1440 passed. Populated browser checks assert letterbox offsets below 1px for both previews. Screenshots are explicitly labeled geometry fixtures, not experiment data. Physical camera/ROI validation not performed. Windows app.js/styles.css updated and hashes matched.

This supersedes the earlier laptop height-cap design notes. Pump behavior and the compact STOP button were not changed in this update.
