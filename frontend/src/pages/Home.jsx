import React from "react";
import {
  Box,
  Button,
  Container,
  Typography,
  Grid,
  Card,
  CardContent,
  CardMedia,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  useTheme,
  useMediaQuery,
} from "@mui/material";
import {
  MedicalServices,
  CheckCircle,
  HowToReg,
  Assessment,
  People,
  Info,
  ExpandMore,
  Phone,
  Email,
} from "@mui/icons-material";

const Home = () => {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  // Datos para las secciones
  const benefits = [
    {
      icon: <MedicalServices fontSize="large" color="primary" />,
      title: "Detección temprana",
      description:
        "Nuestro modelo de IA analiza tus imágenes mamarias con una precisión del 95% para detectar anomalías.",
    },
    {
      icon: <CheckCircle fontSize="large" color="success" />,
      title: "Seguridad y privacidad",
      description:
        "Tus datos están cifrados y protegidos bajo estándares HIPAA/GDPR.",
    },
    {
      icon: <HowToReg fontSize="large" color="secondary" />,
      title: "Fácil de usar",
      description:
        "Sube tus imágenes en segundos y obtén resultados inmediatos con explicaciones detalladas.",
    },
  ];

  const steps = [
    {
      number: 1,
      title: "Regístrate",
      description:
        "Crea una cuenta gratuita en menos de 2 minutos con tu correo electrónico.",
    },
    {
      number: 2,
      title: "Sube tus imágenes",
      description:
        "Sube tus imágenes de mamografía o BUSI en formato JPG/PNG/DICOM.",
    },
    {
      number: 3,
      title: "Recibe tu informe",
      description:
        "Nuestro sistema de IA analiza tus imágenes y genera un reporte detallado.",
    },
    {
      number: 4,
      title: "Consulta a un especialista",
      description:
        "Si es necesario, agenda una consulta con un oncólogo para una evaluación profesional.",
    },
  ];

  const faqs = [
    {
      question: "¿Cómo garantizan la precisión de sus análisis?",
      answer:
        "Utilizamos modelos de IA entrenados con miles de imágenes médicas certificadas, con una precisión del 95% en detección de cáncer de mama.",
    },
    {
      question: "¿Mis datos están seguros?",
      answer:
        "Sí. Cumplimos con los estándares HIPAA y GDPR. Tus imágenes y datos personales están cifrados y protegidos.",
    },
    {
      question: "¿Puedo usar la app si no soy médico?",
      answer:
        "¡Claro! Nuestra plataforma está diseñada tanto para pacientes como para profesionales de la salud.",
    },
    {
      question: "¿Qué tipos de imágenes aceptan?",
      answer:
        "Aceptamos mamografías en formato DICOM y BUSI en JPG/PNG. También puedes subir imágenes de autoexploración.",
    },
  ];

  return (
    <Box sx={{ backgroundColor: "#f5f7fa", minHeight: "100vh" }}>
      {/* Hero Section */}
      <Box
        sx={{
          background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
          color: "white",
          py: 10,
          textAlign: "center",
        }}
      >
        <Container maxWidth="lg">
          <Typography variant="h2" component="h1" gutterBottom sx={{ fontWeight: 700 }}>
            Detección de Cáncer de Mama con IA
          </Typography>
          <Typography variant="h5" sx={{ mb: 4, maxWidth: "800px", mx: "auto" }}>
            Nuestra plataforma utiliza inteligencia artificial para analizar tus imágenes mamarias y detectar anomalías con precisión.
            <br />
            <strong>¡Protege tu salud hoy mismo!</strong>
          </Typography>
          <Button
            variant="contained"
            size="large"
            sx={{
              backgroundColor: "#ff6b6b",
              "&:hover": { backgroundColor: "#ff5252" },
              px: 4,
              py: 2,
              fontSize: "1.2rem",
            }}
            href="/register"
          >
            Comenzar ahora
          </Button>
        </Container>
      </Box>

      {/* ¿Por qué elegirnos? */}
      <Container maxWidth="lg" sx={{ py: 8 }}>
        <Typography
          variant="h3"
          component="h2"
          gutterBottom
          sx={{ textAlign: "center", fontWeight: 600, mb: 6 }}
        >
          ¿Por qué elegirnos?
        </Typography>
        <Grid container spacing={4}>
          {benefits.map((benefit, index) => (
            <Grid item xs={12} md={4} key={index}>
              <Card
                sx={{
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  boxShadow: 3,
                  borderRadius: 2,
                  transition: "transform 0.3s",
                  "&:hover": { transform: "translateY(-5px)" },
                }}
              >
                <CardContent sx={{ flexGrow: 1, textAlign: "center" }}>
                  <Box sx={{ mb: 2 }}>{benefit.icon}</Box>
                  <Typography variant="h5" component="h3" gutterBottom sx={{ fontWeight: 600 }}>
                    {benefit.title}
                  </Typography>
                  <Typography variant="body1" color="text.secondary">
                    {benefit.description}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Container>

      {/* ¿Cómo funciona? */}
      <Box sx={{ backgroundColor: "#e3f2fd", py: 8 }}>
        <Container maxWidth="lg">
          <Typography
            variant="h3"
            component="h2"
            gutterBottom
            sx={{ textAlign: "center", fontWeight: 600, mb: 6 }}
          >
            ¿Cómo funciona?
          </Typography>
          <Grid container spacing={4}>
            {steps.map((step, index) => (
              <Grid item xs={12} md={3} key={index}>
                <Card
                  sx={{
                    height: "100%",
                    display: "flex",
                    flexDirection: "column",
                    boxShadow: 3,
                    borderRadius: 2,
                    transition: "transform 0.3s",
                    "&:hover": { transform: "translateY(-5px)" },
                  }}
                >
                  <CardContent sx={{ flexGrow: 1, textAlign: "center" }}>
                    <Box
                      sx={{
                        width: 60,
                        height: 60,
                        borderRadius: "50%",
                        backgroundColor: theme.palette.primary.main,
                        color: "white",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        mx: "auto",
                        mb: 2,
                        fontSize: "1.5rem",
                        fontWeight: "bold",
                      }}
                    >
                      {step.number}
                    </Box>
                    <Typography variant="h6" component="h3" gutterBottom sx={{ fontWeight: 600 }}>
                      {step.title}
                    </Typography>
                    <Typography variant="body1" color="text.secondary">
                      {step.description}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* Funcionalidades */}
      <Container maxWidth="lg" sx={{ py: 8 }}>
        <Typography
          variant="h3"
          component="h2"
          gutterBottom
          sx={{ textAlign: "center", fontWeight: 600, mb: 6 }}
        >
          Nuestras funcionalidades
        </Typography>
        <Grid container spacing={4}>
          {[
            {
              icon: <Assessment fontSize="large" color="primary" />,
              title: "Análisis con IA",
              description:
                "Nuestro modelo de IA analiza tus imágenes en segundos y te da un reporte detallado.",
            },
            {
              icon: <People fontSize="large" color="secondary" />,
              title: "Diario de síntomas",
              description:
                "Lleva un registro de cómo se siente tu seno cada día para detectar cambios.",
            },
            {
              icon: <Info fontSize="large" color="success" />,
              title: "Información educativa",
              description:
                "Accede a blogs y guías sobre cáncer de mama para estar informada.",
            },
            {
              icon: <Phone fontSize="large" color="error" />,
              title: "Recordatorios",
              description:
                "Recibe notificaciones para autoexploraciones y chequeos médicos.",
            },
          ].map((feature, index) => (
            <Grid item xs={12} md={6} lg={3} key={index}>
              <Box sx={{ textAlign: "center", p: 2 }}>
                <Box sx={{ mb: 2 }}>{feature.icon}</Box>
                <Typography variant="h6" component="h3" gutterBottom sx={{ fontWeight: 600 }}>
                  {feature.title}
                </Typography>
                <Typography variant="body1" color="text.secondary">
                  {feature.description}
                </Typography>
              </Box>
            </Grid>
          ))}
        </Grid>
      </Container>

      {/* FAQ */}
      <Container maxWidth="md" sx={{ py: 8 }}>
        <Typography
          variant="h3"
          component="h2"
          gutterBottom
          sx={{ textAlign: "center", fontWeight: 600, mb: 6 }}
        >
          Preguntas frecuentes
        </Typography>
        {faqs.map((faq, index) => (
          <Accordion key={index} sx={{ mb: 2, borderRadius: 2, boxShadow: 2 }}>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Typography variant="h6" sx={{ fontWeight: 500 }}>
                {faq.question}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="body1" color="text.secondary">
                {faq.answer}
              </Typography>
            </AccordionDetails>
          </Accordion>
        ))}
      </Container>

      {/* CTA */}
      <Box sx={{ backgroundColor: "#667eea", color: "white", py: 8, textAlign: "center" }}>
        <Container maxWidth="lg">
          <Typography variant="h3" component="h2" gutterBottom sx={{ fontWeight: 600 }}>
            ¿Listo para proteger tu salud?
          </Typography>
          <Typography variant="h5" sx={{ mb: 4 }}>
            Regístrate ahora y obtén tu primer análisis gratis.
          </Typography>
          <Button
            variant="contained"
            size="large"
            sx={{
              backgroundColor: "#ff6b6b",
              "&:hover": { backgroundColor: "#ff5252" },
              px: 4,
              py: 2,
              fontSize: "1.2rem",
            }}
            href="/register"
          >
            Registrarse
          </Button>
        </Container>
      </Box>

      {/* Footer */}
      <Box sx={{ backgroundColor: "#1a1a1a", color: "white", py: 6 }}>
        <Container maxWidth="lg">
          <Grid container spacing={4}>
            <Grid item xs={12} md={4}>
              <Typography variant="h5" component="h3" gutterBottom sx={{ fontWeight: 600 }}>
                BreastGuard
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Detección temprana de cáncer de mama con inteligencia artificial.
              </Typography>
            </Grid>
            <Grid item xs={12} md={2}>
              <Typography variant="h6" component="h3" gutterBottom sx={{ fontWeight: 500 }}>
                Enlaces rápidos
              </Typography>
              <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <Button color="inherit" href="/about" sx={{ justifyContent: "flex-start" }}>
                  Sobre nosotros
                </Button>
                <Button color="inherit" href="/blog" sx={{ justifyContent: "flex-start" }}>
                  Blog
                </Button>
                <Button color="inherit" href="/contact" sx={{ justifyContent: "flex-start" }}>
                  Contacto
                </Button>
              </Box>
            </Grid>
            <Grid item xs={12} md={3}>
              <Typography variant="h6" component="h3" gutterBottom sx={{ fontWeight: 500 }}>
                Contacto
              </Typography>
              <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
                <Typography variant="body2" sx={{ display: "flex", alignItems: "center" }}>
                  <Email sx={{ mr: 1 }} /> soporte@breastguard.com
                </Typography>
                <Typography variant="body2" sx={{ display: "flex", alignItems: "center" }}>
                  <Phone sx={{ mr: 1 }} /> +1 (123) 456-7890
                </Typography>
              </Box>
            </Grid>
            <Grid item xs={12} md={3}>
              <Typography variant="h6" component="h3" gutterBottom sx={{ fontWeight: 500 }}>
                Síguenos
              </Typography>
              <Box sx={{ display: "flex", gap: 2 }}>
                <Button
                  variant="outlined"
                  color="inherit"
                  href="#"
                  sx={{ borderRadius: "50%", minWidth: "40px", minHeight: "40px" }}
                >
                  F
                </Button>
                <Button
                  variant="outlined"
                  color="inherit"
                  href="#"
                  sx={{ borderRadius: "50%", minWidth: "40px", minHeight: "40px" }}
                >
                  T
                </Button>
                <Button
                  variant="outlined"
                  color="inherit"
                  href="#"
                  sx={{ borderRadius: "50%", minWidth: "40px", minHeight: "40px" }}
                >
                  I
                </Button>
              </Box>
            </Grid>
          </Grid>
          <Box sx={{ mt: 4, pt: 2, borderTop: "1px solid #333", textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              © {new Date().getFullYear()} BreastGuard. Todos los derechos reservados.
            </Typography>
            <Typography variant="body2" color="text.secondary">
              <a href="/privacy" style={{ color: "#ff6b6b" }}>
                Política de privacidad
              </a>{" "}
              |{" "}
              <a href="/terms" style={{ color: "#ff6b6b" }}>
                Términos de servicio
              </a>
            </Typography>
          </Box>
        </Container>
      </Box>
    </Box>
  );
};

export default Home;
