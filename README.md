# Context Alt Text Monorepo

AI-powered alternative text generation for WordPress media, with facial recognition and roster management.

[![Tests](https://img.shields.io/badge/tests-163%20passing-success)]() [![PHP](https://img.shields.io/badge/PHP-8.2%2B-777BB4)]() [![WordPress](https://img.shields.io/badge/WordPress-6.0%2B-21759B)]() [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)]()

---

## 🚀 Quick Start

### **New Contributors**

Start here: **[`docs/getting-started.md`](docs/getting-started.md)**

### **WordPress Plugin Development**

```bash
cd apps/wp-context-alt-text
npm install && composer install
./scripts/switch-env.sh local
npm run dev
```

📖 **Full guide:** [`apps/wp-context-alt-text/README.md`](apps/wp-context-alt-text/README.md)

### **Recognition Service Development**

```bash
cd apps/recognition-service
pip install -r requirements_local.txt
./scripts/start_recognition_local.sh start
```

📖 **Full guide:** [`apps/recognition-service/README.md`](apps/recognition-service/README.md)

---

## 📦 Monorepo Structure

```
context-alt-text-monorepo/
├── apps/
│   ├── wp-context-alt-text/      # WordPress Plugin (PHP + TypeScript/React)
│   └── recognition-service/      # Face Recognition API (Python FastAPI + InsightFace)
├── packages/
│   ├── shared-contracts/         # TypeScript API contracts between services
│   └── wp-testing-helpers/       # WordPress PHPUnit test utilities
├── docs/                         # Monorepo documentation
│   ├── getting-started.md       # 👈 Start here
│   ├── architecture/            # System design, UML diagrams
│   ├── literature/              # Reference materials
│   └── PROMPTS_INDEX.md         # Agentic development prompts
└── scripts/                      # Monorepo-level scripts
```

---

## 📚 Documentation

### Monorepo-Level

- **[Getting Started](docs/getting-started.md)** - Contributor onboarding
- **[Architecture](docs/architecture/)** - System design, UML diagrams
- **[Prompts Index](docs/PROMPTS_INDEX.md)** - Agentic development

### Project-Specific

**WordPress Plugin:**
- [README](apps/wp-context-alt-text/README.md) - Quick start
- [Configuration](apps/wp-context-alt-text/docs/configuration.md) - Environment profiles
- [Development](apps/wp-context-alt-text/docs/development.md) - Contributing guide
- [API Reference](apps/wp-context-alt-text/docs/api-reference.md) - REST API
- [Troubleshooting](apps/wp-context-alt-text/docs/troubleshooting.md) - Common issues

**Recognition Service:**
- [README](apps/recognition-service/README.md) - Complete documentation

---

## 🏗️ Architecture

```
WordPress Admin (React/TypeScript)
         │
         ├─> Dashboard     (Coverage metrics)
         ├─> Workbench     (Media management, recognition trigger)
         └─> Roster UI     (Entity management)
         │
         ▼
   REST API (cat/v1)
   (PHP Backend)
         │
         ├─> Settings      (Configuration)
         ├─> Recognition   (Job management)
         ├─> Observations  (Face detection results)
         └─> Roster        (Entity CRUD, sync with recognition service)
         │
         ▼
Recognition Service
(Python FastAPI + InsightFace)
         │
         ├─> Face Detection
         ├─> Face Recognition (w600k model)
         └─> Roster Management
```

📖 **Detailed architecture:** [`docs/architecture/`](docs/architecture/)

---

## 🧪 Testing

### WordPress Plugin
```bash
cd apps/wp-context-alt-text
composer test              # PHP tests (PHPUnit)
npm run test              # TypeScript tests (Vitest)
```

**Status:** 163 PHP tests, 653 assertions, all passing ✅

### Recognition Service
```bash
cd apps/recognition-service
pytest --cov=analysis --cov=recognition_core
```

---

## 🤝 Contributing

1. **Read** [`docs/getting-started.md`](docs/getting-started.md)
2. **Choose** a project (WordPress plugin or recognition service)
3. **Set up** your development environment
4. **Find** an issue labeled [`good-first-issue`](https://github.com/darce/context-alt-text-monorepo/labels/good-first-issue)
5. **Follow** [Conventional Commits](https://www.conventionalcommits.org/)

```bash
# Create feature branch
git checkout -b feature/<description>

# Commit from monorepo root
git add apps/ packages/ docs/
git commit -m "feat: add roster import feature"
```

📖 **Full guide:** [`docs/getting-started.md#contributing`](docs/getting-started.md#contributing)

---

## 🚢 Deployment

### WordPress Plugin
```bash
cd apps/wp-context-alt-text
./scripts/switch-env.sh production
npm run build
# Deploy to WordPress hosting
```

### Recognition Service
```bash
# Deploy to Hugging Face Space
git remote add hf git@hf.co:spaces/dearce/recognition-service
git subtree push --prefix=apps/recognition-service hf main
```

---

## 📞 Support

- **Documentation:** [`docs/`](docs/) and project-specific docs
- **Issues:** [GitHub Issues](https://github.com/darce/context-alt-text-monorepo/issues)
- **Discussions:** [GitHub Discussions](https://github.com/darce/context-alt-text-monorepo/discussions)

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

**Key Points:**
- ✅ Commercial use permitted
- ✅ Modification and redistribution allowed
- ✅ Can include other MIT-licensed libraries
- ⚠️ No warranty or liability
