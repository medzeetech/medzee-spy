# Estrutura

```
medzee-spy/
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   ├── structure-base.md          # README curto do boilerplate
│   └── app/
│       ├── main.py                # FastAPI app + lifespan + CORS + /health
│       ├── api/
│       │   └── router.py          # api_router raiz (VAZIO — só comentário do padrão)
│       ├── clients/
│       │   └── supabase.py        # get_supabase_client / get_supabase_admin_client
│       ├── contracts/
│       │   └── responses.py       # SuccessResponse / ErrorResponse / PaginatedResponse
│       ├── core/
│       │   ├── config.py          # Settings (pydantic-settings)
│       │   ├── dependencies.py    # get_db (alias para supabase)
│       │   └── security.py        # bearer auth → supabase.auth.get_user
│       ├── modules/               # VAZIO — destino dos módulos de feature
│       ├── workers/               # VAZIO — destino dos background tasks
│       └── tests/
│           └── conftest.py        # fixture `client` (TestClient) — sem testes ainda
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.js
│   ├── postcss.config.js
│   ├── eslint.config.js
│   ├── public/
│   │   ├── favicon.svg
│   │   └── icons.svg
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                 # BrowserRouter + rotas (MainFlow, /spy, /app/*)
│       ├── index.css               # tailwind + keyframes globais
│       ├── assets/                 # áudios (Marina) + svgs + banner
│       ├── constants/
│       │   └── colors.js           # paleta duplicada (também em tailwind.config)
│       ├── data/
│       │   └── reportData.js       # TODOS os dados do relatório (mockados)
│       ├── components/
│       │   ├── Logo.jsx
│       │   ├── AudioVisualizer.jsx
│       │   └── report/             # seções do relatório (Hero, Funnel, Voice, ...)
│       └── screens/
│           ├── AgentScreen.jsx     # Marina (ElevenLabs)
│           ├── QRScreen.jsx        # QR mockado (URL fixa)
│           ├── GeneratingScreen.jsx
│           ├── LeadFormScreen.jsx
│           ├── ReportScreen.jsx
│           ├── SpyFlow.jsx         # fluxo /spy
│           └── dashboard/
│               ├── DashboardLayout.jsx
│               ├── DashboardPage.jsx
│               ├── ReportsListPage.jsx
│               ├── ReportDetailPage.jsx
│               └── WhatsAppPage.jsx
│
├── memory/                         # memória do agente (auto-managed)
├── .specs/                         # ESTE diretório — spec-driven artifacts
└── package-lock.json               # provável artefato (ver CONCERNS)
```

## Diretórios a criar (M1)
- `backend/app/modules/auth/`
- `backend/app/modules/whatsapp/`
- `backend/app/modules/reports/`
- `backend/app/clients/llm.py`
- `whatsapp-sidecar/` (Node + Baileys) — novo workspace na raiz
