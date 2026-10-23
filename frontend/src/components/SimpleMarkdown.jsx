import { Box, Link, Typography } from '@mui/material';

// Renderiza el subconjunto de markdown que usan nuestros textos (títulos, listas, **negritas**,
// *cursivas* y enlaces [texto](https://...)). Sin dangerouslySetInnerHTML: todo se pinta como
// texto, y solo se enlazan URLs https (nunca javascript: ni rutas relativas).
const LINK = /^\[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/;

function inline(text) {
  return text.split(/(\[[^\]]+\]\(https:\/\/[^)\s]+\)|\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) => {
    const link = part.match(LINK);
    if (link) {
      return (
        <Link key={i} href={link[2]} target="_blank" rel="noopener noreferrer">
          {link[1]}
        </Link>
      );
    }
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('*') && part.endsWith('*')) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export default function SimpleMarkdown({ source }) {
  const blocks = [];
  let list = [];
  const flushList = () => {
    if (list.length) {
      blocks.push(
        <Box component="ul" key={`ul-${blocks.length}`} sx={{ pl: 3, my: 1 }}>
          {list.map((item, i) => (
            <Typography component="li" variant="body2" key={i} sx={{ mb: 0.5 }}>
              {inline(item)}
            </Typography>
          ))}
        </Box>,
      );
      list = [];
    }
  };

  source.split('\n').forEach((raw) => {
    const line = raw.trim();
    if (line.startsWith('- ')) {
      list.push(line.slice(2));
      return;
    }
    flushList();
    if (!line) return;
    if (line.startsWith('## ')) {
      blocks.push(
        <Typography variant="subtitle1" component="h3" key={blocks.length} sx={{ mt: 2, fontWeight: 600 }}>
          {line.slice(3)}
        </Typography>,
      );
    } else if (line.startsWith('# ')) {
      blocks.push(
        <Typography variant="h6" component="h2" key={blocks.length}>
          {line.slice(2)}
        </Typography>,
      );
    } else {
      blocks.push(
        <Typography variant="body2" key={blocks.length} sx={{ my: 1 }}>
          {inline(line)}
        </Typography>,
      );
    }
  });
  flushList();
  return <Box>{blocks}</Box>;
}
