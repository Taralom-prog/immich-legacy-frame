"""Print the <script> of app/index.html, for the ES5 check in CI (`npx es-check es5`)."""
import pathlib
import re

html = pathlib.Path(__file__).resolve().parent.parent.joinpath("app", "index.html").read_text()
print(re.search(r"<script>(.*?)</script>", html, re.S).group(1).replace("/*CONFIG*/{}", "{}"))
