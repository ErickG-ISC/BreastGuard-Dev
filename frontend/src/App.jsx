import { CssBaseline, ThemeProvider, createTheme } from '@mui/material';
import { BrowserRouter as Router, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Home from './pages/Home';
import Login from './pages/Login';
import Register from './pages/Register';
import PatientHome from './pages/patient/PatientHome';
import Questionnaire from './pages/patient/Questionnaire';
import Tenants from './pages/admin/Tenants';

const theme = createTheme({
  colorSchemes: { light: true, dark: true },
  palette: { primary: { main: '#b0306a' } },
});

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
              path="/paciente"
              element={
                <ProtectedRoute roles={['patient']}>
                  <PatientHome />
                </ProtectedRoute>
              }
            />
            <Route
              path="/cuestionario"
              element={
                <ProtectedRoute roles={['patient']}>
                  <Questionnaire />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/tenants"
              element={
                <ProtectedRoute roles={['platform_admin']}>
                  <Tenants />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
