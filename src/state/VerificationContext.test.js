/**
 * The verification settings, held once for the app.
 *
 * These pin the two properties the design turns on: one value shared by every
 * consumer (the coupling is the feature, not a side effect), and a hook that
 * throws outside its provider rather than handing back private defaults —
 * because a panel scoring at its own threshold is exactly the defect this
 * context removes, and it would look like working software.
 */
import { act, render, screen } from '@testing-library/react';

import {
  VerificationProvider, useVerification, defaultThresholdFor,
} from './VerificationContext';
import { VERIFICATION_DEFAULTS } from '../constants';

const Probe = ({ name }) => {
  const v = useVerification();
  return (
    <div>
      <span data-testid={`${name}-threshold`}>{String(v.threshold)}</span>
      <span data-testid={`${name}-hours`}>{v.hourMin}-{v.hourMax}</span>
      <span data-testid={`${name}-fss`}>{v.fssWindow}</span>
      <span data-testid={`${name}-box`}>{v.boxCells}</span>
      <button onClick={() => v.setThreshold('5')}>{`${name}-set`}</button>
    </div>
  );
};

describe('the settings are one copy for the whole tree', () => {
  it('starts every consumer at the shared defaults', () => {
    render(
      <VerificationProvider>
        <Probe name="a" /><Probe name="b" />
      </VerificationProvider>
    );
    expect(screen.getByTestId('a-hours')).toHaveTextContent(
      `${VERIFICATION_DEFAULTS.HOUR_MIN}-${VERIFICATION_DEFAULTS.HOUR_MAX}`);
    expect(screen.getByTestId('a-fss')).toHaveTextContent(String(VERIFICATION_DEFAULTS.FSS_WINDOW));
    expect(screen.getByTestId('b-box')).toHaveTextContent(String(VERIFICATION_DEFAULTS.BOX_CELLS));
  });

  it('shows one consumer what another one changed', () => {
    // The whole point of the design: the two scored tabs are two consumers,
    // and before this they each kept their own threshold.
    render(
      <VerificationProvider>
        <Probe name="a" /><Probe name="b" />
      </VerificationProvider>
    );
    expect(screen.getByTestId('b-threshold')).toHaveTextContent('25');
    act(() => { screen.getByText('a-set').click(); });
    expect(screen.getByTestId('a-threshold')).toHaveTextContent('5');
    expect(screen.getByTestId('b-threshold')).toHaveTextContent('5');
  });

  it('seeds the threshold from the variable, in its own units', () => {
    expect(defaultThresholdFor('precipitation')).toBe(25);
    expect(defaultThresholdFor('wind')).toBe(10);
    render(<VerificationProvider variable="wind"><Probe name="w" /></VerificationProvider>);
    expect(screen.getByTestId('w-threshold')).toHaveTextContent('10');
  });

  it('refuses to work outside its provider', () => {
    // `useRun` throws for the same reason: silently defaulting would make a
    // panel score at a threshold nothing on screen reports.
    const quiet = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Probe name="orphan" />)).toThrow(/useVerification must be used inside/);
    quiet.mockRestore();
  });
});
