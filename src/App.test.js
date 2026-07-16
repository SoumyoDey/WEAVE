import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';

test('renders the WEAVE application shell', () => {
  render(<App />);
  expect(screen.getAllByText('WEAVE').length).toBeGreaterThan(0);
  expect(screen.getByRole('button', { name: 'Visualization' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Analysis' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Comparison' })).toBeInTheDocument();
});

test('exposes keyboard-friendly advanced and map controls', () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Advanced' }));

  const increaseBuckets = screen.getByRole('button', { name: 'Increase number of buckets' });
  expect(increaseBuckets).toBeInTheDocument();
  fireEvent.click(increaseBuckets);

  expect(screen.getByRole('switch', { name: 'Flip colours' })).toHaveAttribute('aria-checked', 'false');
  expect(screen.getByRole('button', { name: 'Rectangle selection' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
});
