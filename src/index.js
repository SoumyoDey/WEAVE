import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import { RunProvider } from './state/RunContext';
import reportWebVitals from './reportWebVitals';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    {/* Outside App so the run resolves once for the whole tree, and so a
        future per-tab selector can override it for a subtree rather than
        every consumer having to change. */}
    <RunProvider>
      <App />
    </RunProvider>
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
