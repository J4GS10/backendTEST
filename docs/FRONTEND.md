# Frontend (React + TypeScript)

Raíz: `backend/inventarioTI-frontend/`. SPA con React 19, TypeScript 5.9 (strict),
Vite 7. Servida por Nginx; `/api/*` se proxya al backend.

## Stack

| Librería | Versión | Uso |
|---|---|---|
| react / react-dom | 19.2 | UI |
| react-router-dom | 7.9 | Routing + RBAC por ruta |
| @mui/material, @mui/icons-material | 7.3 | Componentes e iconos |
| @emotion/react, @emotion/styled | 11 | CSS-in-JS (motor de MUI) |
| axios | 1.13 | Cliente HTTP + interceptores |
| react-hook-form + @hookform/resolvers + zod | 7 / 5 / 4 | Formularios y validación |
| i18next, react-i18next, i18next-browser-languagedetector | 25 / 16 / 8 | i18n (es/en/it) |
| notistack | 3 | Snackbars |
| jwt-decode | 4 | Decodificar JWT en cliente |
| zustand | 5 | Estado (disponible) |

**DevDeps:** typescript 5.9, vite 7, @vitejs/plugin-react, eslint 9 + typescript-eslint,
eslint-plugin-react-hooks/refresh, @types/*.

**Scripts:** `npm run dev` (Vite) · `npm run build` (`tsc -b && vite build`) ·
`npm run lint` · `npm run preview`.

## Estructura `src/`

```
main.tsx · App.tsx · index.css · i18n.ts
api/        axios.ts (cliente + interceptores) · tokenStorage.ts · downloadCsv.ts
components/ Sidebar · LanguageSwitcher · ConfirmDialog · ErrorBoundary · SearchInput
context/    AuthContext (sesión) · ConfigContext (config visual global)
router/     ProtectedRoute (RBAC) · navigation.ts (items del menú por rol)
theme/      theme.ts (tema dinámico) · contrast.ts (WCAG)
locales/    es.json · en.json · it.json  (520 claves c/u, paridad total)
types/      auth · inventory · catalogs · users · consumables · procurement · …
features/   auth · dashboard · assets · catalogs/{brands,models,types} · locations ·
            departments · persons · users · operations · software · consumables ·
            procurement/{providers,orders,warranties} · maintenance · attachments ·
            audit · config
```

### Patrón de feature
`XPage.tsx` (pantalla) + `XDialog.tsx` (crear/editar con react-hook-form) +
`XService.ts` (API axios) + tipos en `src/types/`.

## Autenticación y datos

- **AuthContext** — `user = { sub, role, exp }`. Al cargar intenta refresh por cookie
  HttpOnly; valida el JWT localmente (`jwt-decode`).
- **tokenStorage** — access token en **memoria** (inmune a XSS persistente), refresh en
  cookie HttpOnly gestionada por el navegador.
- **axios.ts** — `baseURL=/api/v1`, `withCredentials`. Interceptor de request inyecta
  `Bearer`; el de response hace **refresh transparente** ante 401 (con mutex para evitar
  refrescos paralelos) y redirige a `/login` si falla. *No fija `Content-Type` global*
  (deja que el navegador ponga `multipart/form-data` con boundary en subidas de archivos).
- **ConfigContext** — carga `GET /gov/config` y expone `{config, isLoaded, reload}`;
  bloquea el render hasta tener config (evita "flash").

## Theming con contraste WCAG (`src/theme/`)

- **contrast.ts** — utilidades matemáticas puras (WCAG 2.1): `relativeLuminance`,
  `contrastRatio`, `mix`, `pickText`, `muteText`, `ensureReadable`.
- **theme.ts** — `createAppTheme(primario, secundario, fondo)` deriva del color de
  **fondo** todos los tokens garantizando legibilidad: `text.primary` (máximo contraste,
  ~AAA), `text.secondary` (≥4.5 atenuado), `divider`, `background.paper`, acento primario
  legible y paleta de estado (success/warning/error/info). El modo (claro/oscuro) se
  decide por la luminancia del fondo. Los colores vienen de `SYS_Color_Primario /
  _Secundario / _Fondo` (configurables en la página de Configuración).
- Las pantallas usan **tokens del tema** (`text.primary`, `background.paper`, `divider`,
  `primary.main`…) en vez de colores fijos, por lo que el contraste se mantiene con
  cualquier fondo.

## Internacionalización

`src/i18n.ts` carga `es/en/it` (bundled). Detección: `localStorage → navigator`,
fallback `es`. Uso: `const { t } = useTranslation(); t('clave', 'fallback')`.
**520 claves por idioma con paridad total** (verificable comparando los 3 JSON).
`LanguageSwitcher` cambia idioma y persiste en localStorage.

## Routing y RBAC en UI

`App.tsx` define las rutas; `ProtectedRoute allowedRoles={[…]}` redirige si el rol no
está permitido (defensa en profundidad — el backend valida igualmente).

| Zona | Roles |
|---|---|
| Dashboard | todos los autenticados |
| Activos, Movimientos, Mantenimiento, Consumibles | SUPER_ADMIN, ADMIN_TI, TECNICO |
| Empleados, Usuarios, Software, Compras, Catálogos | SUPER_ADMIN, ADMIN_TI |
| Configuración, Auditoría | SUPER_ADMIN |

`CONSULTA` ve el dashboard y los datos en modo lectura (no aparece en rutas de escritura).

## Build / deploy

- `vite build` → `/dist` (estáticos con hash).
- Dockerfile multi-stage: Node 20 (build) → Nginx 1.27 (runtime).
- `nginx.conf`: sirve la SPA (fallback a `index.html`), proxya `/api` al backend,
  cabeceras de seguridad (CSP, X-Frame-Options, etc.), gzip, cache de assets, límite de
  subida 20M.
- Variable de build: `VITE_API_URL` (default `/api/v1`).
