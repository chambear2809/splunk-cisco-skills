# Framework Notes

The Splunk Browser RUM agent is framework-agnostic: it patches the global
`fetch` / `XMLHttpRequest` / `addEventListener` / History API surfaces and
works the same on every JS framework. This page captures the per-framework
deployment patterns that make the most sense in Kubernetes.

## React (CRA, Vite, Next.js, Remix, Gatsby)

| Setup | Recommended mode | Notes |
|-------|------------------|-------|
| CRA / Vite SPA built into static `dist/` served by `nginx:alpine` | `nginx-configmap` | Most common case. ConfigMap injection works without source changes. |
| Next.js (SSR) on Node | `runtime-config` or source-side `_app.tsx` init | Next.js renders HTML server-side; sub_filter on a Node container is awkward. Easier to call `SplunkRum.init` in `_app.tsx` `useEffect`. |
| Remix (SSR) | Same as Next.js | |
| Gatsby (SSG) | `nginx-configmap` | SSG output is static HTML. |
| Micro-frontends (multiple sub-apps) | Each sub-app gets its own SplunkRum.init call with a distinct `applicationName` | Filter dashboards by app to slice. |

For React Error Boundaries that swallow errors, see
[manual-instrumentation.md](manual-instrumentation.md) — wire `SplunkRum.error()`
into `componentDidCatch`.

## Vue / Nuxt

| Setup | Recommended mode | Notes |
|-------|------------------|-------|
| Vue SPA built into `dist/` served by nginx | `nginx-configmap` | Same as React SPA. |
| Nuxt 3 (SSR / Universal) | `runtime-config` or source-side `app.vue` init | Nuxt config in `app.vue` `onMounted` runs only client-side. |
| Vue 2 | Source-side `Vue.config.errorHandler` for error capture (see manual-instrumentation.md) | |

## Angular

| Setup | Recommended mode | Notes |
|-------|------------------|-------|
| Angular CLI build served by nginx | `nginx-configmap` | Standard pattern. |
| Angular Universal (SSR) | `runtime-config` or source-side `APP_INITIALIZER` | |
| Angular 2+ | Custom `ErrorHandler` for error capture | |

## SvelteKit

| Setup | Recommended mode | Notes |
|-------|------------------|-------|
| SvelteKit static adapter | `nginx-configmap` | |
| SvelteKit Node adapter (SSR) | `runtime-config` or source-side `+layout.svelte` init | |

## Plain HTML / multi-page apps

| Setup | Recommended mode | Notes |
|-------|------------------|-------|
| nginx serving multiple HTML pages | `nginx-configmap` | sub_filter rewrites every served HTML response. |
| Apache `httpd` | `init-container` | Easier than configuring `mod_substitute`. |
| Custom static-file server | `init-container` | Generic-purpose. |

## Multi-tenant subdomain patterns

When you serve the same SPA on multiple subdomains (`tenant1.app.com`,
`tenant2.app.com`, ...) and want the RUM session to follow the user across
subdomains, set `cookie_domain` to the parent domain:

```yaml
cookie_domain: ".app.com"
```

This sets the `__splunk_rum_sid` cookie's domain to `.app.com` so all
subdomains share the same session ID. Without this, each subdomain gets its
own session.

## iframe-embedded apps

When your frontend is loaded inside an iframe (e.g., Confluence macro,
Salesforce Lightning component), the RUM agent runs in the iframe's context.
The Session Replay recorder cannot reach across the iframe boundary unless:

- The host page also includes the recorder (rare).
- You set `features.iframes: true` AND the iframes are same-origin AND your
  CSP allows the recorder script in the iframe context.

Cross-origin iframes can never be recorded by Session Replay (browser
security boundary).

## WebView in mobile apps

WebView pages running inside an iOS or Android app share the user's session
ID with the native RUM agent if the native side passes the
`splunk.rumSessionId` attribute through. This is a one-time wiring on the
mobile-app side; see the Splunk RUM iOS or Android docs for the per-platform
recipe. This skill does not cover the mobile side.

## Service Workers

Service Workers run in their own context outside the page's `window`. The
RUM agent cannot run in a Service Worker. If your app aggressively caches
with a Service Worker, ensure the cached HTML still contains the rendered
RUM snippet (cache the rewritten file, not the original).

## Streaming SSR (React 18+, SvelteKit, etc.)

The rendered RUM snippet must arrive in the very first chunk of the streamed
HTML response, before `</head>` closes. Most streaming SSR frameworks
flush `<head>` early enough that nginx sub_filter can still match. If your
framework chunks `<head>` across multiple network reads, switch to mode B
(runtime-config) or wire `SplunkRum.init` in your `_app` / `app.vue` /
`+layout.svelte` directly.
