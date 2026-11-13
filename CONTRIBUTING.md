# Contributing

Thanks for helping! A few rules keep this project working on the devices it was made for:

- **`app/index.html` must run on Safari 9 (iOS 9).** ES5 only: `var` and `function`, no
  `let`/`const`, arrow functions, template strings, `fetch` or `classList.toggle(…, force)`;
  no CSS `object-fit` or grid. CI checks the JavaScript with `es-check es5`.
- **No dependencies** in `app/server.py`: the Python standard library and ffmpeg only.
- Run the tests before opening a pull request: `python3 -m unittest discover tests`.
- If you can, test on a real old device and say which one (model and iOS version) in your
  pull request.

When reporting a bug, please include your device and iOS version, your Immich version, and
the relevant lines of `docker compose logs`.
