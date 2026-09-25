/* Cockpit Financeiro — imita o `claude.use(...)` do runtime de artifacts do Claude e manda
   tudo para a API do Django (cockpitFinanceiro/views.py). Cobre só o que o painel usa:
     db:        doc('col/id').get/set/delete · collection(c).orderBy(f, dir).limit(n).get()
                · collection(c).add(obj) · collection(c).doc(id).delete()
     assets:    upload(file, {type}) → {id, url} · delete(id)
     user:      id() → nome de quem entrou · profiles([ids]) → {id: {name}}
     downloads: save({filename, data: Blob})
   Qualquer outro nome devolve null, e o painel já trata "recurso indisponível". */
(function () {
  'use strict';
  var BASE = location.pathname.replace(/[^/]*$/, '');   // ".../financeiro/"

  function erro(code, message) { var e = new Error(message || code); e.code = code; return e; }

  function req(metodo, caminho, corpo, ehForm) {
    var opts = { method: metodo, credentials: 'same-origin', headers: { 'X-Cockpit': '1' } };
    if (corpo !== undefined) {
      if (ehForm) { opts.body = corpo; }
      else { opts.body = JSON.stringify(corpo); opts.headers['Content-Type'] = 'application/json'; }
    }
    return fetch(BASE + caminho, opts).then(function (r) {
      if (r.status === 401) { location.reload(); throw erro('unauthenticated'); }
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 403 && j.erro === 'somente_leitura') throw erro('permission_denied', 'Seu acesso é só de leitura.');
        if (!r.ok) throw erro(r.status === 400 ? 'invalid_argument' : 'unavailable', j.erro);
        return j;
      });
    });
  }

  function snap(j) {
    return { id: j.id, exists: !!j.exists, data: function () { return j.data; } };
  }

  function docRef(colecao, id) {
    var p = 'api/db/' + encodeURIComponent(colecao) + '/' + encodeURIComponent(id);
    return {
      id: id,
      get: function () { return req('GET', p).then(snap); },
      set: function (obj) { return req('PUT', p, obj).then(function () {}); },
      delete: function () { return req('DELETE', p).then(function () {}); },
    };
  }

  function consulta(colecao, ordem, dir, limite) {
    return {
      orderBy: function (campo, d) { return consulta(colecao, campo, d || 'asc', limite); },
      limit: function (n) { return consulta(colecao, ordem, dir, n); },
      get: function () {
        var q = '?ordem=' + encodeURIComponent(ordem || '') + '&dir=' + encodeURIComponent(dir || '')
              + '&limite=' + encodeURIComponent(limite || 200);
        return req('GET', 'api/colecao/' + encodeURIComponent(colecao) + q).then(function (j) {
          var docs = (j.docs || []).map(snap);
          return { docs: docs, empty: !docs.length, size: docs.length };
        });
      },
    };
  }

  var db = {
    doc: function (caminho) {
      var partes = String(caminho).split('/');
      return docRef(partes[0], partes[1]);
    },
    collection: function (colecao) {
      var c = consulta(colecao);
      c.add = function (obj) {
        return req('POST', 'api/colecao/' + encodeURIComponent(colecao), obj)
          .then(function (j) { return docRef(colecao, j.id); });
      };
      c.doc = function (id) { return docRef(colecao, id); };
      return c;
    },
  };

  var assets = {
    upload: function (file, opts) {
      var fd = new FormData();
      fd.append('arquivo', file);
      fd.append('tipo', (opts && opts.type) || file.type || '');
      return req('POST', 'api/anexos', fd, true);
    },
    delete: function (id) { return req('DELETE', 'api/anexos/' + encodeURIComponent(id)); },
  };

  var eu = null;
  var user = {
    id: function () {
      if (!eu) eu = req('GET', 'api/eu').then(function (j) { return j.id; });
      return eu;
    },
    // O "id" gravado nos documentos já é o nome de quem entrou.
    profiles: function (ids) {
      var out = {};
      (ids || []).forEach(function (id) { if (id) out[id] = { name: id }; });
      return Promise.resolve(out);
    },
  };

  var downloads = {
    save: function (o) {
      var url = URL.createObjectURL(o.data);
      var a = document.createElement('a');
      a.href = url; a.download = o.filename || 'arquivo';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
      return Promise.resolve({ ok: true });
    },
  };

  var recursos = { db: db, assets: assets, user: user, downloads: downloads };
  window.claude = {
    use: function (nome) { return Promise.resolve(recursos[nome] || null); },
  };

  // Perfil só leitura: esconde carregar planilha e enviar/excluir anexos. O servidor também
  // recusa (403) — esconder é só para não oferecer o que não vai funcionar.
  var css = document.createElement('style');
  css.textContent = 'html.cockpit-leitura #syncbar-btn, html.cockpit-leitura #syncbar-file,'
    + 'html.cockpit-leitura [id^="doc-"][id$="-btn"], html.cockpit-leitura [id^="doc-"][id$="-file"],'
    + 'html.cockpit-leitura [id^="doc-"][id$="-delete"] { display: none !important; }';
  document.documentElement.appendChild(css);
  req('GET', 'api/eu').then(function (j) {
    if (!j.pode_editar) document.documentElement.classList.add('cockpit-leitura');
  }).catch(function () {});

  // "Trocar senha" e "Sair" discretos no canto (a sessão dura 12 h).
  document.addEventListener('DOMContentLoaded', function () {
    var estilo = 'font:12px system-ui,sans-serif;padding:6px 10px;border-radius:6px;'
      + 'border:1px solid rgba(127,127,127,.4);background:rgba(127,127,127,.12);color:inherit;'
      + 'cursor:pointer;text-decoration:none;display:inline-block';
    var f = document.createElement('form');
    f.method = 'post'; f.action = BASE + 'sair';
    f.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:99999;margin:0;display:flex;gap:6px';
    f.innerHTML = '<a href="' + BASE + 'trocar-senha" style="' + estilo + '">Trocar senha</a>'
      + '<button type="submit" style="' + estilo + '">Sair</button>';
    document.body.appendChild(f);
  });
})();
