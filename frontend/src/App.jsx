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
import SelfExam from './pages/patient/SelfExam';
import Reminders from './pages/patient/Reminders';
import Blog from './pages/patient/Blog';
import BlogArticle from './pages/patient/BlogArticle';
import Unsubscribe from './pages/Unsubscribe';
import Tenants from './pages/admin/Tenants';
import TenantDetail from './pages/admin/TenantDetail';
import PlatformLog from './pages/admin/PlatformLog';
import InstitutionUsers from './pages/institution/Users';
import InstitutionLog from './pages/institution/Log';
import AcceptInvitation from './pages/AcceptInvitation';
import DoctorHome from './pages/doctor/DoctorHome';
import AdminShell from './components/AdminShell';
import { BusinessIcon, HomeIcon, LogIcon, PeopleIcon } from './components/icons';
import theme from './theme';

const PLATFORM_NAV = [
  { label: 'Tenants', to: '/admin/tenants', icon: BusinessIcon },
  { label: 'Auditoría de plataforma', to: '/admin/auditoria', icon: LogIcon },
];
const INSTITUTION_NAV = [
  { label: 'Usuarios', to: '/institucion/usuarios', icon: PeopleIcon },
  { label: 'Bitácora', to: '/institucion/bitacora', icon: LogIcon },
];
// Provisional hasta el panel médico (CU-11), que traerá su propio shell
const DOCTOR_NAV = [{ label: 'Inicio', to: '/medico', icon: HomeIcon }];

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
            <Route path="/baja" element={<Unsubscribe />} />
            <Route path="/invitacion" element={<AcceptInvitation />} />
            {/* Administración de plataforma (wireframe D04) */}
            <Route
              element={
                <ProtectedRoute roles={['platform_admin']}>
                  <AdminShell title="Admin de plataforma" items={PLATFORM_NAV} />
                </ProtectedRoute>
              }
            >
              <Route path="/admin/tenants" element={<Tenants />} />
              <Route path="/admin/tenants/:id" element={<TenantDetail />} />
              <Route path="/admin/auditoria" element={<PlatformLog />} />
            </Route>
            {/* Administración de la institución (tenant_admin, su tenant) */}
            <Route
              element={
                <ProtectedRoute roles={['tenant_admin']}>
                  <AdminShell title="Admin de la institución" items={INSTITUTION_NAV} />
                </ProtectedRoute>
              }
            >
              <Route path="/institucion/usuarios" element={<InstitutionUsers />} />
              <Route path="/institucion/bitacora" element={<InstitutionLog />} />
            </Route>
            {/* Médica: por ahora, aceptar traspasos de pacientes (0014) */}
            <Route
              element={
                <ProtectedRoute roles={['doctor']}>
                  <AdminShell title="Médica" items={DOCTOR_NAV} />
                </ProtectedRoute>
              }
            >
              <Route path="/medico" element={<DoctorHome />} />
            </Route>
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
              <Route path="/autoexploracion" element={<SelfExam />} />
              <Route path="/recordatorios" element={<Reminders />} />
              <Route path="/informacion" element={<Blog />} />
              <Route path="/informacion/:slug" element={<BlogArticle />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
