import { CssBaseline, ThemeProvider } from '@mui/material';
import { BrowserRouter as Router, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import PatientShell from './components/PatientShell';
import ProtectedRoute from './components/ProtectedRoute';
import Home from './pages/Home';
import Login from './pages/Login';
import Register from './pages/Register';
import PatientHome from './pages/patient/PatientHome';
import Questionnaire from './pages/patient/Questionnaire';
import Analyze from './pages/patient/Analyze';
import Result from './pages/patient/Result';
import History from './pages/patient/History';
import Diary from './pages/patient/Diary';
import More from './pages/patient/More';
import Tenants from './pages/admin/Tenants';
import theme from './theme';

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/registro" element={<Register />} />
            <Route
              path="/admin/tenants"
              element={
                <ProtectedRoute roles={['platform_admin']}>
                  <Tenants />
                </ProtectedRoute>
              }
            />
            {/* App de paciente: barra inferior en móvil, barra lateral en escritorio */}
            <Route
              element={
                <ProtectedRoute roles={['patient']}>
                  <PatientShell />
                </ProtectedRoute>
              }
            >
              <Route path="/paciente" element={<PatientHome />} />
              <Route path="/cuestionario" element={<Questionnaire />} />
              <Route path="/analizar" element={<Analyze />} />
              <Route path="/resultado/:id" element={<Result />} />
              <Route path="/historial" element={<History />} />
              <Route path="/diario" element={<Diary />} />
              <Route path="/mas" element={<More />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
