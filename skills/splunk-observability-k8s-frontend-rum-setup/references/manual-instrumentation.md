# Manual Instrumentation

The `@splunk/otel-web` 2.x SDK exposes a small public API for cases the
auto-instrumentation does not cover: custom workflow spans (which appear on
the DEA Custom Events tab), per-user attribution, manual error reporting, and
per-framework error-handler integration.

This skill renders only the K8s-side delivery of the agent; the API calls
described here go in your application source. Use the snippets below as
starting points.

## Public API surface

```typescript
import SplunkRum from '@splunk/otel-web';

SplunkRum.init({ /* config */ });

// Add or update global attributes after init.
SplunkRum.setGlobalAttributes({
  'enduser.id': 'u_42',
  'enduser.role': 'admin',
});

// Get the current session ID (e.g., to surface in your support form).
const sessionId = SplunkRum.getSessionId();

// Manually report an error (typically from a framework error handler).
SplunkRum.error(new Error('checkout-step-3 failed'), { customer_tier: 'gold' });
```

When using the CDN build, all calls must be guarded with `if (window.SplunkRum)`
to avoid breaking when an ad-blocker prevents the agent from loading.

## User attribution

The Browser RUM agent does not auto-link traces to your authenticated users.
Add `enduser.id` and `enduser.role` either at init time (when the value is
known up front) or via `setGlobalAttributes` after auth completes:

```javascript
import SplunkRum from '@splunk/otel-web';

const user = await fetch('/api/me').then((r) => r.json());
SplunkRum.setGlobalAttributes({
  'enduser.id': user.id,
  'enduser.role': user.role,
  'tenant.id': user.tenantId,
});
```

Spans emitted before `setGlobalAttributes` runs will not carry the
attributes; only later spans will. This is normal and not a bug.

## Custom workflow spans (DEA Custom Events)

A span with a `workflow.name` attribute appears on the Splunk RUM UI's
Event Definitions > Custom Events tab. Use this for business-level actions
that are not URL changes (e.g., "user liked a post").

```javascript
import { trace } from '@opentelemetry/api';

const tracer = trace.getTracer('blog');
const span = tracer.startSpan('blog.likes', {
  attributes: {
    'workflow.name': 'blog.likes',
    'post.id': postId,
  },
});
// time passes (could be sync or async)
span.end();
```

To mark a workflow span as failed:

```javascript
const span = tracer.startSpan('test.module.load', {
  attributes: {
    'workflow.name': 'test.module.load',
    error: true,
    'error.message': 'Custom workflow error message',
  },
});
span.end();
```

The `@opentelemetry/api` package version must match the major version used by
`@splunk/otel-web`. Check with:

```javascript
window[Symbol.for('opentelemetry.js.api.1')].version
```

## SPA route changes

The Splunk RUM agent automatically captures route changes via History API
patching when the `document` instrumentation is enabled (default ON). No
manual instrumentation is needed for `pushState` / `replaceState` /
`hashchange`-driven SPAs. The emitted spans are zero-duration `routeChange`
spans with `prev.href` and `location.href` attributes.

For per-component instrumentation (e.g., timing how long a particular React
component took to render after a route change), wrap with a custom span:

```javascript
import { trace } from '@opentelemetry/api';

function ProfileRoute() {
  const tracer = trace.getTracer('app');
  const span = tracer.startSpan('profile.render');
  useEffect(() => () => span.end(), []);
  return <ProfileContent />;
}
```

## Per-framework error handlers

Splunk RUM auto-captures uncaught JS errors via `window.onerror` and
`window.onunhandledrejection`, but framework error boundaries that catch
errors swallow them before they reach the global handlers. Wire the framework
handler to call `SplunkRum.error(...)` so caught errors still flow to RUM.

### React

```javascript
import React from 'react';
import SplunkRum from '@splunk/otel-web';

class ErrorBoundary extends React.Component {
  componentDidCatch(error, errorInfo) {
    if (window.SplunkRum) SplunkRum.error(error, errorInfo);
  }
  render() { return this.props.children; }
}
```

### Vue 3

```javascript
import { createApp } from 'vue';
import SplunkRum from '@splunk/otel-web';

const app = createApp(App);
app.config.errorHandler = function (err, instance, info) {
  if (window.SplunkRum) SplunkRum.error(err, info);
};
app.mount('#app');
```

### Vue 2

```javascript
import Vue from 'vue';
import SplunkRum from '@splunk/otel-web';

Vue.config.errorHandler = function (err, vm, info) {
  if (window.SplunkRum) SplunkRum.error(err, info);
};
```

### Angular 2+

```typescript
import { ErrorHandler, NgModule } from '@angular/core';
import SplunkRum from '@splunk/otel-web';

class SplunkErrorHandler implements ErrorHandler {
  handleError(error: any) {
    if ((window as any).SplunkRum) SplunkRum.error(error);
  }
}

@NgModule({ providers: [{ provide: ErrorHandler, useClass: SplunkErrorHandler }] })
class AppModule {}
```

### Angular 1

```javascript
import SplunkRum from '@splunk/otel-web';

angular.module('app').factory('$exceptionHandler', () => function (exception, cause) {
  if (window.SplunkRum) SplunkRum.error(exception, cause);
});
```

### Ember

```javascript
import Ember from 'ember';
import SplunkRum from '@splunk/otel-web';

Ember.onerror = function (err) {
  if (window.SplunkRum) SplunkRum.error(err);
};
```

## Sanitizing PII before export

The `exporter.onAttributesSerializing` callback gives you a chance to mutate
or drop attributes before they leave the browser. Use it to strip query-string
secrets, mask email addresses in URLs, etc.

```javascript
SplunkRum.init({
  // ...
  exporter: {
    onAttributesSerializing: (attributes, span) => {
      if (attributes['http.url']) {
        attributes['http.url'] = String(attributes['http.url'])
          .replace(/secret=[^&]+/g, 'secret=***');
      }
      return attributes;
    },
  },
});
```

The Browser RUM agent automatic instrumentation does not collect or report
request payloads or POST bodies (only their size).
