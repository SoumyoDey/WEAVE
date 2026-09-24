import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';
import { RunProvider } from './state/RunContext';

/**
 * App reads the selected run from context, so it has to be rendered inside the
 * provider that `index.js` supplies in production. `useRun` throws rather than
 * defaulting when the provider is missing, deliberately — a component that
 * silently rendered with no run would send unqualified requests, which work
 * against one run and 400 against two. Mirroring production here is the fix;
 * softening the guard would not be.
 */
const renderApp = () => render(<RunProvider><App /></RunProvider>);

test('renders the WEAVE application shell', () => {
  renderApp();
  expect(screen.getAllByText('WEAVE').length).toBeGreaterThan(0);
  expect(screen.getByRole('button', { name: 'Visualization' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Analysis' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Comparison' })).toBeInTheDocument();
});

test('exposes keyboard-friendly advanced and map controls', () => {
  renderApp();
  fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));

  const increaseBuckets = screen.getByRole('button', { name: 'Increase number of buckets' });
  expect(increaseBuckets).toBeInTheDocument();
  fireEvent.click(increaseBuckets);

  expect(screen.getByRole('switch', { name: 'Flip colours' })).toHaveAttribute('aria-checked', 'false');
  expect(screen.getByRole('button', { name: 'Rectangle selection' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
});
