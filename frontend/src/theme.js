import { createTheme } from '@mui/material';

// Tema único de la app (wireframes de docs/wireframes). Las páginas no definen colores, radios
// ni tipografía propios: todo sale de aquí para que claro y oscuro se vean coherentes.
const BRAND = '#b0306a';

const theme = createTheme({
  // Variables CSS con el esquema del sistema operativo (prefers-color-scheme)
  cssVariables: true,
  colorSchemes: {
    light: {
      palette: {
        primary: { main: BRAND },
        secondary: { main: '#5f6b7a' },
        background: { default: '#fafafa', paper: '#ffffff' },
        divider: '#e0e0e0',
        text: { primary: '#2b2b2b', secondary: '#616161' },
        // Fondo de visores de ecografía y heatmap (las imágenes médicas se ven sobre negro)
        imaging: { main: '#000000', contrastText: '#ffffff' },
      },
    },
    dark: {
      palette: {
        primary: { main: '#e07aa6' },
        secondary: { main: '#a7b1bd' },
        background: { default: '#121214', paper: '#1c1c20' },
        imaging: { main: '#000000', contrastText: '#ffffff' },
      },
    },
  },
  shape: { borderRadius: 12 },
  typography: {
    // Pila del sistema: sin fuentes externas (privacidad y carga en móvil)
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif',
    h4: { fontWeight: 700 },
    h5: { fontWeight: 700 },
    h6: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { borderRadius: 999, paddingInline: 20, minHeight: 44 } },
    },
    MuiTextField: { defaultProps: { variant: 'outlined', fullWidth: true } },
    MuiCard: { defaultProps: { variant: 'outlined' } },
    MuiPaper: {
      styleOverrides: {
        // Las tarjetas y paneles (elevación 1, la predeterminada) se ven planos con borde;
        // menús y diálogos conservan su sombra
        root: ({ ownerState, theme: t }) =>
          ownerState.variant === 'elevation' && ownerState.elevation === 1
            ? { boxShadow: 'none', border: `1px solid ${t.vars.palette.divider}` }
            : {},
      },
    },
    MuiChip: { styleOverrides: { root: { borderRadius: 999 } } },
    MuiAppBar: { defaultProps: { elevation: 0, color: 'inherit' } },
    MuiBottomNavigationAction: {
      styleOverrides: { root: { minWidth: 0, paddingInline: 4 } },
    },
  },
});

export default theme;
