"""Bundle the same library interface as a packaged Chrome extension page."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parent
static=root/'unscroll'/'static'
target=root/'extension'
html=(static/'index.html').read_text().replace('/static/style.css','style.css').replace('/static/app.js','app.js').replace('href="/"','href="library.html"')
(target/'library.html').write_text(html)
for name in ('app.js','style.css'):shutil.copyfile(static/name,target/name)
print('Bundled Unscroll library into extension/library.html')
