# JavaScript Source Map Upload

Without source maps, JavaScript error stack traces in Splunk RUM look like:

```
TypeError: o is undefined
    at e.<anonymous> (main.min.js:1:23042)
    at t.<anonymous> (vendor.min.js:1:9847)
```

With source maps uploaded, the same error in the RUM UI becomes:

```
TypeError: o is undefined
    at CheckoutFlow.handleSubmit (src/components/CheckoutFlow.tsx:142:18)
    at FormProvider.onSubmit (src/lib/Form.tsx:67:9)
```

The skill renders helpers that wire the `splunk-rum` CLI into your CI pipeline
so source maps upload on every production build. The token used for upload is
the **Org Access Token** (`SPLUNK_O11Y_TOKEN_FILE`), NOT the RUM token. Source
map upload happens server-to-server (your CI -> Splunk), not browser-to-server.

## Workflow overview

```
1. Production build -> dist/main.<hash>.js + dist/main.<hash>.js.map
2. splunk-rum sourcemaps inject --path dist
   -> appends `//# sourceMappingURL=...?sourceMapId=<sha>` and a comment
      to every .js file so the agent knows which map to fetch.
3. splunk-rum sourcemaps upload --path dist --app-name X --app-version Y
   -> POSTs every .js.map to Splunk RUM, tagged with applicationName +
      app.version so the UI can correlate runtime errors back to the right
      bundle.
4. Deploy dist/ to your CDN / pod / K8s ConfigMap as usual.
```

The `applicationName` and `app.version` you pass on upload MUST match the
values in your `SplunkRum.init({ applicationName, version })` call. If they
diverge, the RUM UI cannot match a runtime stack to an uploaded map and you
get the mangled output again.

## Rendered files

When `source_maps.enabled: true` (default), the skill emits:

| File | Purpose |
|------|---------|
| `source-maps/sourcemap-upload.sh` | Wraps `splunk-rum sourcemaps inject` and `... upload`. Reads `SPLUNK_O11Y_TOKEN_FILE`, `SPLUNK_O11Y_REALM`, `APP_NAME`, `APP_VERSION` from env. |
| `source-maps/github-actions.yaml` | Drop-in GitHub Actions job (only when `ci_provider: github_actions`). |
| `source-maps/gitlab-ci.yaml` | Drop-in GitLab CI job (only when `ci_provider: gitlab_ci`). |
| `source-maps/splunk.webpack.js` | Webpack 5 config that uses `@splunk/rum-build-plugins` to inject + upload at build time (only when `bundler: webpack`). |

## CLI mode (default)

The `splunk-rum` CLI works for any bundler (Webpack, Vite, Rollup, esbuild,
Parcel, Next.js, Nuxt). Install once:

```bash
npm install -g @splunk/rum-cli
```

Run after the build:

```bash
export SPLUNK_O11Y_TOKEN_FILE=/path/to/splunk-org-token   # chmod 600
export SPLUNK_O11Y_REALM=us0
export APP_NAME=acme-checkout                              # matches SplunkRum.init applicationName
export APP_VERSION=1.42.0                                  # matches SplunkRum.init version
bash splunk-observability-k8s-frontend-rum-rendered/source-maps/sourcemap-upload.sh
```

The wrapper sets `SPLUNK_REALM` and `SPLUNK_ACCESS_TOKEN` (read from the file)
before invoking the CLI, so you never put the token on the command line or
in shell history.

## Webpack plugin mode

If you use Webpack 5, you can fold inject + upload into the build itself:

```javascript
// webpack.config.js
const { SplunkRumWebpackPlugin } = require('@splunk/rum-build-plugins');

module.exports = {
  devtool: 'source-map',
  plugins: [
    new SplunkRumWebpackPlugin({
      applicationName: 'acme-checkout',
      version: process.env.APP_VERSION || 'dev',
      sourceMaps: {
        token: process.env.SPLUNK_ACCESS_TOKEN,
        realm: process.env.SPLUNK_O11Y_REALM,
        disableUpload: process.env.NODE_ENV !== 'production',
      },
    }),
  ],
};
```

`disableUpload: true` is the right default for local dev (you don't want every
`webpack --watch` save to upload a fresh map). Flip it to `false` in CI.

The skill renders this snippet at `source-maps/splunk.webpack.js` when the
spec sets `source_maps.bundler: webpack`. Copy the relevant parts into your
existing `webpack.config.js` — don't replace the whole file.

## CI snippets

### GitHub Actions

```yaml
name: Upload Splunk RUM source maps
on:
  push:
    branches: [main]
jobs:
  upload-sourcemaps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install splunk-rum CLI
        run: npm install -g @splunk/rum-cli
      - name: Build production bundle
        run: npm ci && npm run build
      - name: Upload source maps
        env:
          SPLUNK_O11Y_REALM: ${{ vars.SPLUNK_O11Y_REALM }}
          SPLUNK_ACCESS_TOKEN: ${{ secrets.SPLUNK_O11Y_ORG_TOKEN }}
          APP_NAME: ${{ vars.APP_NAME }}
          APP_VERSION: ${{ github.sha }}
        run: |
          splunk-rum sourcemaps inject --path dist
          splunk-rum sourcemaps upload --path dist \
              --app-name "${APP_NAME}" \
              --app-version "${APP_VERSION}"
```

Use the `${{ github.sha }}` as the `APP_VERSION` so each commit gets its own
map. This also requires you to set the same value in `SplunkRum.init({ version })`
at runtime (typically via a build-time env-var injected into your bundle).

### GitLab CI

```yaml
upload-sourcemaps:
  stage: deploy
  image: node:20
  variables:
    SPLUNK_O11Y_REALM: "${SPLUNK_O11Y_REALM}"
    SPLUNK_ACCESS_TOKEN: "${SPLUNK_O11Y_ORG_TOKEN}"
    APP_NAME: "${APP_NAME}"
    APP_VERSION: "${CI_COMMIT_SHA}"
  script:
    - npm install -g @splunk/rum-cli
    - npm ci
    - npm run build
    - splunk-rum sourcemaps inject --path dist
    - splunk-rum sourcemaps upload --path dist --app-name "${APP_NAME}" --app-version "${APP_VERSION}"
  only:
    - main
```

## sourcesContent option

Source maps can either reference your source files by path (small map) or
embed the source content (`sourcesContent` field, large map). Embedding is
required for the RUM UI to display the actual source line for each frame:

```javascript
// webpack.config.js
module.exports = {
  devtool: 'source-map',  // includes sourcesContent by default
};
```

For Next.js:

```javascript
// next.config.js
module.exports = {
  productionBrowserSourceMaps: true,
};
```

If your build tool generates source maps without `sourcesContent`, the RUM
UI shows the file path and line number but not the source code itself.

## Privacy considerations

Uploading source maps means Splunk RUM has access to the readable form of
your minified JavaScript bundle. If your bundle contains code you do not want
Splunk to see (proprietary algorithms in client-side code, etc.), either:

- Generate source maps **without** `sourcesContent` (file-path-only maps).
- Skip source-map upload entirely and accept the mangled stack traces.

Splunk RUM stores source maps permanently. There is no UI to delete an
uploaded source map; contact Splunk Support if you need to delete one.

## Validation

```bash
bash splunk-observability-k8s-frontend-rum-rendered/scripts/validate.sh \
  --check-source-maps --source-map-dir dist
```

Runs `splunk-rum sourcemaps verify --path dist` to confirm every `.js` in the
target directory has a corresponding `.js.map` and a properly-injected
`sourceMapId`.

## Troubleshooting

**Stack traces still mangled in the RUM UI**:
- `applicationName` mismatch between `SplunkRum.init` and `--app-name`.
- `app.version` mismatch between `SplunkRum.init({ version })` and `--app-version`.
- The minified `.js` file in production is a different build than the one whose
  `.js.map` was uploaded (re-run `inject + upload` on the exact `dist/` you
  deploy).

**Upload fails with 401**:
- Token file is the RUM token, not the Org Access Token. Source-map upload
  needs Org Access Token.
- Token has expired or been rotated.

**Upload fails with 413 (payload too large)**:
- A single source map is over the per-file size limit. Split the bundle into
  smaller chunks (Webpack `splitChunks`) so each `.js.map` stays under the
  limit.
