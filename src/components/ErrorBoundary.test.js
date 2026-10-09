/**
 * The boundary contains a throw, names what died, and lets go again.
 *
 * Before this existed, the four tabs shared one React tree with no boundary in
 * it, so **any render throw blanked the whole application** — map, run
 * selector and three healthy tabs going down with the one that broke
 * (`NEXT_STEPS.md` §70).
 *
 * These tests throw for real rather than asserting on the fallback's markup in
 * isolation. Rendering `<ErrorBoundary><div>…</div></ErrorBoundary>` and
 * checking it shows its children proves nothing about the only behaviour that
 * matters, which is what happens when a child throws during render.
 *
 * React logs caught errors to `console.error` by design, and jsdom prints the
 * whole component stack, so the expected noise is silenced per-test — but only
 * after `componentDidCatch`'s own call is captured and asserted on, because a
 * boundary that swallows the stack is the defect this project keeps meeting in
 * other forms.
 */
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { ErrorBoundary } from './ErrorBoundary';

const Boom = ({ when = true, message = 'kaboom' }) => {
  if (when) throw new Error(message);
  return <div>healthy child</div>;
};

let consoleError;
beforeEach(() => {
  consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  consoleError.mockRestore();
});

describe('when nothing throws', () => {
  it('renders its children untouched, with no wrapper of its own', () => {
    // No wrapper matters: the overlays it wraps in App are absolutely
    // positioned, and an extra div would move them.
    const { container } = render(
      <ErrorBoundary name="Analysis"><p>healthy child</p></ErrorBoundary>,
    );
    expect(screen.getByText('healthy child')).toBeInTheDocument();
    expect(container.firstChild.tagName).toBe('P');
  });
});

describe('when a child throws during render', () => {
  it('shows a fallback instead of taking the tree down', () => {
    render(<ErrorBoundary name="Analysis"><Boom /></ErrorBoundary>);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/The Analysis panel stopped/)).toBeInTheDocument();
  });

  it('names the panel, so the reader knows what is still working', () => {
    render(<ErrorBoundary name="Comparison"><Boom /></ErrorBoundary>);
    expect(screen.getByText(/The Comparison panel stopped/)).toBeInTheDocument();
    expect(screen.getByText(/other tabs are still usable/)).toBeInTheDocument();
  });

  it('shows the error message rather than a generic apology', () => {
    render(<ErrorBoundary name="Analysis"><Boom message="cell is not iterable" /></ErrorBoundary>);
    expect(screen.getByText(/cell is not iterable/)).toBeInTheDocument();
  });

  it('logs the error and the component stack', () => {
    render(<ErrorBoundary name="Analysis"><Boom message="kaboom" /></ErrorBoundary>);
    const ours = consoleError.mock.calls.find(
      (args) => typeof args[0] === 'string' && args[0].includes('[ErrorBoundary: Analysis]'),
    );
    expect(ours).toBeTruthy();
    expect(ours[1]).toBeInstanceOf(Error);
    expect(ours[1].message).toBe('kaboom');
    expect(String(ours[2])).toMatch(/Boom/);   // the component stack
  });

  it('calls onError, for a caller that wants to do more than log', () => {
    const onError = jest.fn();
    render(<ErrorBoundary name="Analysis" onError={onError}><Boom /></ErrorBoundary>);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
  });

  it('does not render a sibling boundary\'s fallback', () => {
    // The per-tab arrangement in App: one tab failing must leave the next alone.
    render(
      <>
        <ErrorBoundary name="Analysis"><Boom /></ErrorBoundary>
        <ErrorBoundary name="Comparison"><p>comparison is fine</p></ErrorBoundary>
      </>,
    );
    expect(screen.getByText(/The Analysis panel stopped/)).toBeInTheDocument();
    expect(screen.getByText('comparison is fine')).toBeInTheDocument();
    expect(screen.queryByText(/The Comparison panel stopped/)).not.toBeInTheDocument();
  });
});

describe('recovering', () => {
  it('re-renders the children when "Try again" is pressed and the cause is gone', () => {
    const { rerender } = render(
      <ErrorBoundary name="Analysis"><Boom when /></ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    // The cause goes away (a different point selected, a run that has data).
    rerender(<ErrorBoundary name="Analysis"><Boom when={false} /></ErrorBoundary>);
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));

    expect(screen.getByText('healthy child')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('stays latched if the cause is still there', () => {
    // Resetting into a subtree that throws again must not loop or appear fixed.
    render(<ErrorBoundary name="Analysis"><Boom when /></ErrorBoundary>);
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('resets itself when resetKeys change', () => {
    // How it gets out of the way on a run switch without the user noticing.
    const { rerender } = render(
      <ErrorBoundary name="Analysis" resetKeys={['run-a']}><Boom when /></ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(
      <ErrorBoundary name="Analysis" resetKeys={['run-b']}><Boom when={false} /></ErrorBoundary>,
    );
    expect(screen.getByText('healthy child')).toBeInTheDocument();
  });

  it('does not reset when resetKeys are merely re-created with equal values', () => {
    // A new array every render is the normal case in JSX. Comparing by
    // identity would reset on every render, which re-throws forever.
    const { rerender } = render(
      <ErrorBoundary name="Analysis" resetKeys={['run-a']}><Boom when /></ErrorBoundary>,
    );
    rerender(
      <ErrorBoundary name="Analysis" resetKeys={['run-a']}><Boom when /></ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
