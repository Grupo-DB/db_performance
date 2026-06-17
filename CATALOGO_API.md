# 📦 API de Catálogo - Documentação

## Status: ✅ COMPLETO (Refatorado - v2)

---

## Hierarquia de Modelos

```
Fabricante (ex: Ford, Mercedes, Volvo)
  └─ Veículo (ex: Ranger, Sprinter, FH)
       ├─ Equipamento (ex: Caminhão, Carro, Máquina)
       └─ Seção (ex: Motor, Transmissão, Suspensão)
            └─ Produto (ex: Amortecedor, Rolamento, Corrente)
```

---

## Modelos Implementados

| Modelo | Campos | Relações |
|--------|--------|----------|
| `Fabricante` | id, nome, image, created_at, updated_at | 1:N com Veículo |
| `Equipamento` | id, nome, descricao, ativo, created_at, updated_at | 1:N com Veículo |
| `Veículo` | id, nome, modelo, descricao, ativo, created_at, updated_at | FK: Fabricante, Equipamento |
| `Seção` | id, nome, descricao, ativo, created_at, updated_at | FK: Veículo |
| `Produto` | id, nome, descricao, preco, image, ativo, created_at, updated_at | FK: Veículo, Seção |
| `Pedido` | id, numero_referencia, status, total, observacoes, created_at, updated_at | FK: User |
| `ItemPedido` | id, quantidade, preco_unitario, created_at, updated_at | FK: Pedido, Produto |
| `PedidoNotificacao` | id, tipo, mensagem, lido, created_at | FK: Pedido, User |

---

## 🔌 Endpoints da API

### 1. Fabricantes (Read Only)
```
GET    /api/fabricantes/                    # Listar
GET    /api/fabricantes/{id}/               # Detalhe
```

**Filtros:**
- `search=Ford`
- `ordering=nome` ou `ordering=-created_at`

---

### 2. Equipamentos (CRUD)
```
GET    /api/equipamentos/                   # Listar
POST   /api/equipamentos/                   # Criar
GET    /api/equipamentos/{id}/              # Detalhe
PUT    /api/equipamentos/{id}/              # Atualizar
PATCH  /api/equipamentos/{id}/              # Parcial
DELETE /api/equipamentos/{id}/              # Deletar
```

**Filtros:**
- `search=Caminhão`
- `ativo=true` ou `ativo=false`
- `ordering=nome` ou `ordering=-created_at`

**Payload:**
```json
{
  "nome": "Caminhão",
  "descricao": "Veículos comerciais pesados",
  "ativo": true
}
```

---

### 3. Veículos (CRUD)
```
GET    /api/veiculos/                       # Listar
POST   /api/veiculos/                       # Criar
GET    /api/veiculos/{id}/                  # Detalhe
PUT    /api/veiculos/{id}/                  # Atualizar
PATCH  /api/veiculos/{id}/                  # Parcial
DELETE /api/veiculos/{id}/                  # Deletar
```

**Filtros:**
- `fabricante={id}`
- `equipamento={id}`
- `ativo=true` ou `ativo=false`
- `search=Ranger`
- `ordering=nome` ou `ordering=modelo` ou `ordering=-created_at`

**Payload:**
```json
{
  "nome": "Ranger",
  "modelo": "2024",
  "fabricante": 1,
  "equipamento": 1,
  "descricao": "Caminhão pickup leve",
  "ativo": true
}
```

---

### 4. Seções (CRUD)
```
GET    /api/secoes/                         # Listar
POST   /api/secoes/                         # Criar
GET    /api/secoes/{id}/                    # Detalhe
PUT    /api/secoes/{id}/                    # Atualizar
PATCH  /api/secoes/{id}/                    # Parcial
DELETE /api/secoes/{id}/                    # Deletar
```

**Filtros:**
- `veiculo={id}`
- `ativo=true` ou `ativo=false`
- `search=Motor`
- `ordering=nome` ou `ordering=-created_at`

**Payload:**
```json
{
  "nome": "Motor",
  "veiculo": 1,
  "descricao": "Componentes do motor",
  "ativo": true
}
```

---

### 5. Produtos (CRUD)
```
GET    /api/produtos/                       # Listar
POST   /api/produtos/                       # Criar
GET    /api/produtos/{id}/                  # Detalhe
PUT    /api/produtos/{id}/                  # Atualizar
PATCH  /api/produtos/{id}/                  # Parcial
DELETE /api/produtos/{id}/                  # Deletar
```

**Filtros:**
- `veiculo={id}`
- `secao={id}`
- `ativo=true` ou `ativo=false`
- `search=Amortecedor`
- `ordering=nome` ou `ordering=preco` ou `ordering=-created_at`

**Payload:**
```json
{
  "nome": "Amortecedor Dianteiro",
  "descricao": "Amortecedor original",
  "veiculo": 1,
  "secao": 1,
  "preco": "450.00",
  "image": "arquivo.jpg",
  "ativo": true
}
```

---

### 6. Pedidos (CRUD - Autenticado)
```
GET    /api/pedidos/                        # Listar
POST   /api/pedidos/                        # Criar
GET    /api/pedidos/{id}/                   # Detalhe
PATCH  /api/pedidos/{id}/update_status/    # Mudar Status
POST   /api/pedidos/{id}/cancelar/          # Cancelar
```

**Autenticação:** Token obrigatório

**Filtros:**
- `status=RASCUNHO`
- `usuario={id}`
- `created_at` 
- `ordering=-created_at`

**Status choices:**
- `RASCUNHO` (padrão)
- `ENVIADO`
- `RECEBIDO`
- `EM_COTACAO`
- `APROVADO`
- `REJEITADO`
- `REALIZADO`
- `CANCELADO`

**Payload POST (criar):**
```json
{
  "observacoes": "Entregar até dia 30",
  "itens": [
    {
      "produto": 1,
      "quantidade": 2,
      "preco_unitario": "450.00"
    }
  ]
}
```

**Payload PATCH (mudar status):**
```json
{
  "status": "EM_COTACAO",
  "observacoes": "Aguardando cotação"
}
```

---

### 7. Notificações (Autenticado)
```
GET    /api/notificacoes/                   # Listar (filtrado por user)
POST   /api/notificacoes/marcar_como_lido/ # Marcar como lidas
GET    /api/notificacoes/nao_lidas/        # Contar não lidas
```

**Autenticação:** Token obrigatório

**Filtros:**
- `lido=false`
- `ordering=-created_at`

**Payload POST (marcar como lido):**
```json
{
  "notificacao_ids": [1, 2, 3]
}
```

---

## 📊 Exemplo de Fluxo Completo

### 1. Cliente busca produtos
```bash
GET /api/produtos/?veiculo=1&secao=1
```

### 2. Cliente cria pedido
```bash
POST /api/pedidos/
{
  "observacoes": "Urgente",
  "itens": [
    {"produto": 1, "quantidade": 2, "preco_unitario": "450.00"}
  ]
}
```

**Resposta:**
```json
{
  "id": 1,
  "numero_referencia": "PED-000001",
  "usuario": "joao_silva",
  "status": "RASCUNHO",
  "total": "900.00",
  "observacoes": "Urgente",
  "itens": [
    {
      "id": 1,
      "produto": {...},
      "quantidade": 2,
      "preco_unitario": "450.00",
      "subtotal": "900.00"
    }
  ]
}
```

### 3. Gestor atualiza status
```bash
PATCH /api/pedidos/1/update_status/
{
  "status": "EM_COTACAO",
  "observacoes": "Em análise"
}
```

### 4. Cliente verifica notificações
```bash
GET /api/notificacoes/?lido=false
```

---

## 🔐 Autenticação

```
Authorization: Token seu_token_aqui
```

Incluir header em endpoints autenticados:
- POST /api/pedidos/
- PATCH /api/pedidos/{id}/update_status/
- POST /api/pedidos/{id}/cancelar/
- GET /api/notificacoes/
- POST /api/notificacoes/marcar_como_lido/
- GET /api/notificacoes/nao_lidas/

---

## 🎯 Validações Importantes

**Transições de Status permitidas:**
- RASCUNHO → ENVIADO, CANCELADO
- ENVIADO → RECEBIDO, CANCELADO
- RECEBIDO → EM_COTACAO, REJEITADO, CANCELADO
- EM_COTACAO → APROVADO, REJEITADO, CANCELADO
- APROVADO → REALIZADO, CANCELADO
- REJEITADO → RASCUNHO, CANCELADO
- REALIZADO → CANCELADO
- CANCELADO → (nenhuma transição)

**ItemPedido.subtotal:** Calculado automaticamente = quantidade × preco_unitario

**Pedido.total:** Recalculado ao adicionar/remover itens

---

## 💡 Notas Importantes

1. **Campos Hierárquicos:** Produto sempre tem Veículo e Seção definidos
2. **Equipamento opcional:** Veículo deve ter Equipamento e Fabricante
3. **Paginação:** Default 20 itens/página, máx 100
4. **Filtros:** Podem ser combinados (ex: `?veiculo=1&ativo=true&search=Motor`)
5. **Ordem:** Default por nome (exceto Pedidos que é por -created_at)

---

**Atualizado em:** 2026-06-17  
**Versão:** 2.0 - Com hierarquia completa
**Commit:** d3f19f85
