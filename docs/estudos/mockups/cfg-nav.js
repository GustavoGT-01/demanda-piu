// Mockup: liga o menu do diálogo "⚙ Configurações" às telas de cada seção.
(function () {
  var paginas = {rede: '00-configuracoes.html', backup: '01-configuracoes-backup.html', 'e-mail': '04-configuracoes-email.html',
    avisos: '02-configuracoes-avisos.html', servidor: '03-configuracoes-servidor.html'};
  document.querySelectorAll('.cfg-nav button').forEach(function (b) {
    var nome = b.textContent.replace(/[^\p{L}-]/gu, ' ').trim().split(/\s+/)[0].toLowerCase();
    var url = paginas[nome];
    if (!url || b.hasAttribute('aria-current')) return;
    b.style.cursor = 'pointer';
    b.title = 'Abrir a seção ' + b.textContent.trim();
    b.addEventListener('click', function () { location.href = url; });
  });
})();
