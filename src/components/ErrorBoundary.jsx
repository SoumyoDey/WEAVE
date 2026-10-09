/**
 * One tab failing should cost you that tab, not the application.
 *
 * The four tabs live in one React tree and are hidden with `display: none`
 * rather than unmounted, so until now **any render throw anywhere took the
 * whole app with it** — a blank page, with the map, the run selector and the
 * three tabs that were fine going down alongside the one that was not. That is
 * the worst available outcome for a tool whose job is to show numbers: it
 * removes the evidence of what broke along with everything else.
 *
 * Error boundaries are the only React feature that catches a render throw, and
 * they must be class components — `getDerivedStateFromError` and
 * `componentDidCatch` have no hook equivalent. That is why this file is the
 * one class in `src/components`.
 *
 * **What it deliberately does not do:**
 *
 * - *It does not swallow the error.* `componentDidCatch` logs the error and the
 *   component stack to the console. A boundary that renders a tidy message and
 *   drops the stack trades a visible failure for an invisible one, which is the
 *   defect this project keeps finding in other shapes (`NEXT_STEPS.md` §28, §49).
 * - *It does not catch what it cannot catch*, and says so here so nobody
 *   assumes otherwise: React boundaries do not see errors thrown in event
 *   handlers, in `setTimeout`, or in async code after an `await`. Nearly every
 *   failure this app has actually had — a fetch rejecting, a 400 from a scored
 *   endpoint — is in that second category and is already handled by the panels'
 *   own error state. This catches the other kind: a bad shape reaching a
 *   renderer, which is what blanks the page.
 * - *It does not reset itself on a timer or on every render.* Re-rendering the
 *   same broken subtree just throws again. It resets when the user asks, or
 *   when `resetKeys` change — which is how a boundary gets out of the way once
 *   the thing that caused the throw (usually the selected run) has moved on.
 */
import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

import { t } from '../theme';

const shallowEqual = (a = [], b = []) =>
  a.length === b.length && a.every((v, i) => Object.is(v, b[i]));

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Kept as console.error rather than routed anywhere: there is no client
    // error sink in this deployment, and inventing a silent one would be worse
    // than the browser console a developer already has open.
    // eslint-disable-next-line no-console
    console.error(
      `[ErrorBoundary${this.props.name ? `: ${this.props.name}` : ''}]`,
      error,
      info?.componentStack,
    );
    this.props.onError?.(error, info);
  }

  componentDidUpdate(prevProps) {
    // A new run (or whatever the caller keys on) is a new attempt. Without
    // this the boundary would stay latched after the user has already changed
    // the thing that broke it, and the only way out would be a reload.
    if (this.state.error && !shallowEqual(prevProps.resetKeys, this.props.resetKeys)) {
      this.reset();
    }
  }

  reset() {
    this.setState({ error: null });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const { name } = this.props;
    const message = error?.message || String(error);

    return (
      <div
        role="alert"
        style={{
          height: '100%', display: 'flex', alignItems: 'center',
          justifyContent: 'center', padding: '32px', textAlign: 'center',
          color: 'rgba(255,255,255,0.75)',
        }}
      >
        <div style={{ maxWidth: '560px' }}>
          <AlertTriangle size={30} style={{ color: '#e67e22', marginBottom: '14px' }} />

          <p style={{ fontSize: t.fontSize.lg, margin: 0, color: 'rgba(255,255,255,0.85)' }}>
            {name ? `The ${name} panel stopped` : 'This panel stopped'}
          </p>

          {/* Naming the other tabs is the point of the per-tab boundary: the
              reader needs to know the rest of the app is still standing. */}
          <p style={{ fontSize: t.fontSize.base, margin: '10px 0 0 0', color: 'rgba(255,255,255,0.45)' }}>
            Nothing else is affected — the other tabs are still usable, and no
            data was changed.
          </p>

          {/* The message, not a generic apology. Whoever hits this is the same
              person who will have to fix it. */}
          <pre style={{
            margin: '18px 0 0 0', padding: '10px 12px', textAlign: 'left',
            background: 'rgba(0,0,0,0.3)', border: `1px solid ${t.border}`,
            borderRadius: t.radius, color: 'rgba(255,255,255,0.6)',
            fontSize: t.fontSize.xs, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            maxHeight: '140px', overflow: 'auto',
          }}>
            {message}
          </pre>

          <button
            onClick={this.reset}
            style={{
              marginTop: '16px', padding: '8px 16px', cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: '7px',
              background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.8)',
              border: `1px solid ${t.borderStrong}`, borderRadius: t.radius,
              fontSize: t.fontSize.sm,
            }}
          >
            <RotateCcw size={14} /> Try again
          </button>

          <p style={{ fontSize: t.fontSize.xs, margin: '12px 0 0 0', color: 'rgba(255,255,255,0.3)' }}>
            The full stack is in the browser console.
          </p>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
