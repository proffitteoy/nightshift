import { useEffect } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import { Home } from './pages/Home';
import { Analysis } from './pages/Analysis';
import { syncAppSettingsWithEnv } from './services/appSettings';

export default function App() {
  useEffect(() => {
    syncAppSettingsWithEnv();
  }, []);

  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/analysis" element={<Analysis />} />
      </Routes>
    </HashRouter>
  );
}
