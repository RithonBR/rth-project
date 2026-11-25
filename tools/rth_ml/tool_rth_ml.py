# -*- coding: utf-8 -*-
# ============================================================
# FERRAMENTA: RTH Machine Learning — Classificação de Uso do Solo
#
# O que faz (ponto de vista do usuário):
#   O usuário seleciona uma imagem raster multibanda (ex: ortomosaico
#   de drone ou imagem de satélite), uma camada vetorial com polígonos
#   de amostras anotados manualmente por classe de uso do solo, e o
#   campo numérico inteiro que identifica cada classe. Ao clicar em
#   Executar, o plugin:
#     1. Rasteriza as amostras vetoriais no mesmo grid da imagem
#     2. Extrai os valores de pixel de cada amostra para um array numpy
#     3. Treina um modelo de ML (RF, Extra Trees, Gradient Boosting, SVM, KNN, Naive Bayes, GMM Nativo ou GMM sklearn) nesses dados
#     4. Classifica cada pixel da imagem inteira, bloco a bloco
#     5. Salva o resultado como GeoTIFF UInt16 e carrega no projeto
#
#   Opcionalmente: divide as amostras em treino/teste, calcula OA e
#   índice Kappa de Cohen, e exporta a matriz de confusão em CSV.
#
# Como ela se encaixa no ciclo de vida do plugin:
#   Instanciada em RTH PROJECT.py → __init__() como:
#     self.tool_rth_ml = RthMLTool(iface)
#   Acionada pelo item de menu correspondente via:
#     self.tool_rth_ml.run()
#   O diálogo (RthMLDialog) é criado uma vez e reutilizado (singleton).
#   Todo processamento pesado corre em _MLWorker (QThread) para nunca
#   bloquear o event loop do QGIS — a UI fica responsiva durante a classificação.
#
# Classes principais:
#   RthMLTool         → entry point; cria/mostra o diálogo
#   RthMLDialog       → QDialog com formulário de configuração
#   _MLWorker         → QThread que executa toda a computação
#   _GMMR             → implementação GMM nativo em numpy puro (sem sklearn)
#   Modelos sklearn   → RF, Extra Trees, Gradient Boosting, SVM, KNN, Naive Bayes, GMM sklearn (QDA)
#   _PipInstallWorker → QThread auxiliar para instalar scikit-learn
# ============================================================
"""
tool_rth_ml — Classificação de Uso do Solo por Machine Learning
tool_rth_ml — Land Use Classification by Machine Learning

Fluxo / Flow:
  1. Usuário escolhe imagem raster, camada de amostras e campo de classes.
     User picks raster image, samples layer and class field.
  2. Escolhe o modelo (Random Forest ou Gaussian Mixture Model) e parâmetros.
     Picks model (Random Forest or Gaussian Mixture Model) and parameters.
  3. Opcionalmente: split amostral para validação e salvamento da matriz de confusão.
     Optionally: sample split for validation and confusion matrix export.
  4. Worker roda em QThread:
       a. Rasteriza amostras vetoriais (GDAL RasterizeLayer)
       b. Extrai pixels de treinamento bloco a bloco
       c. Treina o modelo
       d. Classifica a imagem inteira bloco a bloco
       e. Salva GeoTIFF e carrega no projeto
     Worker runs in QThread (same steps in EN above).

Adaptado de dzetsaka (Karasiak & Lomellini, GPLv3) — rasterize, get_samples_from_roi
e predict_image reescritos seguindo os padrões RTH PROJECT.
Adapted from dzetsaka (Karasiak & Lomellini, GPLv3) — rasterize, get_samples_from_roi
and predict_image rewritten following RTH PROJECT standards.

# Copyright (C) 2026 Luciano dos Santos Cardoso Junior
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License v3
"""

import os
import tempfile

# Sentinela "sem amostra" no raster ROI gerado por _rasterize_samples.
# Pixels fora de qualquer polígono de amostra recebem este valor, que é então
# ignorado em _get_samples(). UInt16.max = 65535 garante que classe 0 seja
# uma classe válida (sem o sentinela, np.nonzero filtraria a classe 0, deixando
# o modelo com apenas as classes >= 1 — o bug exato que o campo ID_Classe=[0,1] causou).
# "No sample" sentinel in the ROI raster. Pixels outside any training polygon get
# this value and are ignored in _get_samples(). Using 65535 lets class 0 be valid.
_ROI_NODATA = 65535

# numpy e gdal são importados com try/except (deferred check) porque o QGIS
# os inclui na sua distribuição, mas instalações corrompidas ou alternativas
# (ex: QGIS via conda) podem não tê-los. Guardamos flags booleanos em vez de
# importar direto: assim o plugin carrega sem travar mesmo se faltarem.
# O erro só aparece quando o usuário tenta executar (_check_deps verifica os flags).
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

try:
    from osgeo import gdal, ogr
    _HAS_GDAL = True
except ImportError:
    _HAS_GDAL = False

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QFileDialog,
    QProgressBar, QFrame, QGroupBox, QMessageBox,
)
from qgis.core import (
    Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsContrastEnhancement, QgsRasterMinMaxOrigin,
)

# ── Compatibilidade Qt5 (QGIS 3) / Qt6 (QGIS 4) ─────────────────────────────
#
# O QGIS 3 usa Qt 5 e o QGIS 4 usa Qt 6. No Qt 6 vários valores de enum
# foram movidos para sub-namespaces tipados. Exemplo:
#   Qt 5: QMessageBox.Warning
#   Qt 6: QMessageBox.Icon.Warning
#
# A estratégia: tentar primeiro o caminho do Qt 6 (mais novo) e, se falhar
# com AttributeError, cair no caminho do Qt 5. Guardamos em constantes de
# módulo (_MB_ICON_WARNING etc.) para que o código que usa esses valores
# não precise repetir o try/except em todo lugar.
try:
    _MB_ICON_WARNING = QMessageBox.Icon.Warning          # Qt6 / QGIS 4
except AttributeError:
    _MB_ICON_WARNING = QMessageBox.Warning               # Qt5 / QGIS 3

# QMessageBox.AcceptRole / RejectRole → ButtonRole.AcceptRole / ButtonRole.RejectRole no Qt6
try:
    _MB_ACCEPT_ROLE = QMessageBox.ButtonRole.AcceptRole  # Qt6 / QGIS 4
    _MB_REJECT_ROLE = QMessageBox.ButtonRole.RejectRole  # Qt6 / QGIS 4
except AttributeError:
    _MB_ACCEPT_ROLE = QMessageBox.AcceptRole             # Qt5 / QGIS 3
    _MB_REJECT_ROLE = QMessageBox.RejectRole             # Qt5 / QGIS 3

# QgsContrastEnhancement.StretchToMinimumMaximum → algoritmo de esticamento
# que mapeia [min_pixel, max_pixel] para [0, 255] na visualização.
# QgsRasterMinMaxOrigin.MinMax → diz ao QGIS para calcular min/max a partir
# dos valores reais do raster (não de uma estimativa por amostragem).
# Sem isso, a classificação UInt16 (valores 1, 2, 3…) aparece quase preta.
try:
    _CE_STRETCH = QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum
    _CE_LIMITS  = QgsRasterMinMaxOrigin.Limits.MinMax
except AttributeError:
    _CE_STRETCH = QgsContrastEnhancement.StretchToMinimumMaximum
    _CE_LIMITS  = QgsRasterMinMaxOrigin.MinMax


def _check_deps(model_key):
    """Verifica dependências antes de iniciar o worker /
    Check dependencies before starting the worker.

    Fazemos essa verificação ANTES de criar o QThread para dar feedback
    imediato ao usuário — é muito melhor mostrar um erro em 0ms do que
    deixar o worker iniciar e falhar no meio da classificação.

    Retorna:
      None                 → tudo ok, pode iniciar o worker
      ('error', msg)       → numpy ou gdal faltando — mostrar QMessageBox fatal
      ('no_sklearn', None) → sklearn ausente para RF — oferecer instalação
    """
    if not _HAS_NUMPY:
        return ('error',
            'NumPy não encontrado — é necessário para processar a imagem.\n'
            'Normalmente já vem com o QGIS. Verifique sua instalação.\n\n'
            'NumPy not found — required to process the image.\n'
            'It normally ships with QGIS. Check your installation.')
    if not _HAS_GDAL:
        return ('error',
            'GDAL/OGR não encontrado — é necessário para ler/escrever rasters.\n'
            'Normalmente já vem com o QGIS. Verifique sua instalação.\n\n'
            'GDAL/OGR not found — required to read/write rasters.\n'
            'It normally ships with QGIS. Check your installation.')
    # Apenas o GMM Nativo ('GMM') usa implementação numpy pura — todos os outros
    # modelos dependem do scikit-learn. Verificamos com um import leve (sklearn.__version__).
    if model_key != 'GMM':
        try:
            import sklearn  # noqa: F401
        except ImportError:
            return ('no_sklearn', None)
    return None


# ── Instalador de dependências em background ──────────────────────────────────

class _PipInstallWorker(QThread):
    # QThread é a forma correta de rodar código pesado (I/O, rede, CPU) sem
    # travar o QGIS. O QGIS é single-threaded na UI: se rodarmos pip install
    # na thread principal, a janela congela e o usuário pensa que travou.
    # Ao herdar de QThread e sobrescrever run(), dizemos ao Qt "rode isso em
    # outra thread". O Qt cria e gerencia a thread por baixo dos panos.
    """Roda `pip install <pacote>` em background sem travar a UI /
    Runs `pip install <package>` in background without blocking the UI."""

    # pyqtSignal é o mecanismo de comunicação thread-safe entre threads no Qt.
    # NÃO podemos chamar métodos de UI diretamente da thread secundária —
    # isso causa crashes. Em vez disso, emitimos um sinal com .emit() na thread
    # secundária, e o Qt entrega a chamada na thread principal de forma segura.
    finished = pyqtSignal(bool, str)   # (sucesso, mensagem de erro)
    status   = pyqtSignal(str)         # linha de progresso do pip → atualiza label na UI em tempo real

    def __init__(self, package, parent=None):
        super().__init__(parent)
        self._package = package

    def run(self):
        # run() é o método que o Qt chama automaticamente ao iniciar a thread
        # via .start(). Tudo que estiver aqui roda fora da thread principal.
        # Nunca tocar em widgets Qt aqui — só emitir sinais.
        import sys
        import os
        import subprocess
        # CREATE_NO_WINDOW (Windows) evita que o subprocess abra uma janela de console preta.
        # No Linux/Mac o atributo não existe, então getattr retorna 0 (sem efeito).
        _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            python_exe = self._find_python_exe()
            # Popen + leitura linha a linha: o pip transmite "Downloading...", "Installing..."
            # em tempo real para a UI via sinal status.
            # --no-color: remove escape ANSI que poluiria o label.
            # stderr=STDOUT: combina os dois streams para capturar mensagens de erro.
            # creationflags=_no_win: impede a janela de console preta no Windows.
            proc = subprocess.Popen(
                [python_exe, '-m', 'pip', 'install', '--no-color', self._package],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, creationflags=_no_win)
            output_lines = []
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    output_lines.append(line)
                    self.status.emit(line)
            proc.wait(timeout=300)
            if proc.returncode == 0:
                self.finished.emit(True, '')
            else:
                err = '\n'.join(output_lines[-10:]) or 'Erro desconhecido / Unknown error'
                self.finished.emit(False, err)
        except Exception as exc:
            self.finished.emit(False, str(exc))

    @staticmethod
    def _find_python_exe():
        """Localiza o python.exe correto dentro do ambiente QGIS/OSGeo4W.
        Locate the correct python.exe inside the QGIS/OSGeo4W environment.

        No Windows, sys.executable aponta para qgis.exe (não para python.exe).
        A estratégia é: montar candidatos de múltiplas fontes → filtrar pelo nome
        (deve conter 'python', não 'qgis') → validar executando 'import pip'.
        On Windows, sys.executable points to qgis.exe, not python.exe.
        Strategy: collect candidates from multiple sources → filter by name
        (must contain 'python', not 'qgis') → validate by running 'import pip'.
        Baseado na abordagem do QGIS Pip Manager (MohamedShamroukh/QGIS-pip-manager).
        """
        import sys, os, subprocess, sysconfig

        # 1 — Coleta candidatos de todas as fontes conhecidas
        dirs = set()
        try:
            dirs.add(sysconfig.get_config_var('BINDIR') or '')   # diretório bin do Python ativo
        except Exception:
            pass
        for attr in ('exec_prefix', 'prefix', 'base_prefix'):
            dirs.add(getattr(sys, attr, '') or '')

        # sys.path pode conter entradas que levam ao Python (ex: Lib/site-packages → ../../)
        for p in sys.path:
            dirs.add(p)
            dirs.add(os.path.dirname(p))

        # Adiciona o diretório de sys.executable mesmo que seja qgis.exe — as subpastas podem ter python
        dirs.add(os.path.dirname(sys.executable))

        # 2 — Expande cada diretório com os nomes típicos do executável Python
        candidates = []
        for d in dirs:
            if not d:
                continue
            for name in ('python.exe', 'python3.exe', 'python', 'python3'):
                candidates.append(os.path.join(d, name))
                candidates.append(os.path.join(d, 'Scripts', name))

        # 3 — Filtra: arquivo deve existir e nome deve conter 'python' (exclui qgis.exe)
        seen = set()
        filtered = []
        for c in candidates:
            norm = os.path.normcase(os.path.normpath(c))
            if norm in seen:
                continue
            seen.add(norm)
            if not os.path.isfile(c):
                continue
            if 'python' not in os.path.basename(c).lower():
                continue
            filtered.append(c)

        # 4 — Valida: executa 'import pip' e verifica retorno 0 com output (padrão QGIS Pip Manager)
        # CREATE_NO_WINDOW impede janela de console preta durante cada tentativa de validação.
        _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        for path in filtered:
            try:
                r = subprocess.run(
                    [path, '-c', 'import pip; print(pip.__version__)'],
                    capture_output=True, timeout=10, creationflags=_no_win)
                if r.returncode == 0 and r.stdout.strip():
                    return path
            except Exception:
                continue

        # Fallback: sys.executable (funciona em Linux/Mac onde não é qgis.exe)
        return sys.executable


# ── GMMR — Gaussian Mixture Model com regularização Ridge (idêntico ao dzetsaka) ──────

class _GMMR:
    # O Gaussian Mixture Model (GMM) parte do pressuposto de que os pixels
    # de cada classe de uso do solo seguem uma distribuição gaussiana
    # multivariada no espaço espectral (valores das bandas).
    # "Mixture" porque a imagem inteira é modelada como mistura de C gaussianas,
    # uma por classe. Para classificar um pixel, calculamos qual gaussiana
    # tem a maior probabilidade de ter gerado aquele vetor de valores.
    #
    # "Ridge" (regularização de Tikhonov): ao inverter a matriz de covariância
    # (necessário para a distância de Mahalanobis), adicionamos tau à diagonal.
    # Isso evita matrizes singulares quando há poucas amostras — sem regularização,
    # uma classe com N amostras < N_bandas teria covariância não-invertível.
    # Com tau=0.0 (padrão), o comportamento é idêntico ao GMM clássico.
    #
    # Interface: learn(x, y) treina; predict(xt) classifica. Igual ao dzetsaka.
    """Gaussian Mixture Model com regularização Ridge — implementação idêntica à do dzetsaka.
    Gaussian Mixture Model with Ridge regularization — identical to dzetsaka's GMMR.

    Baseado em Mathieu Fauvel (dzetsaka, GPLv3). Usa apenas numpy.linalg — sem sklearn.
    Based on Mathieu Fauvel (dzetsaka, GPLv3). Uses only numpy.linalg — no sklearn.
    """

    def __init__(self):
        # Todos os arrays são inicializados como listas vazias e preenchidos em learn().
        # Indexados por classe c (c=0,1,...,C-1).
        self.ni       = []   # ni[c]      → número de amostras da classe c
        self.prop     = []   # prop[c]    → proporção da classe c no total de amostras
        self.mean     = []   # mean[c,:]  → vetor médio (centróide) da classe c, shape (d,)
        self.cov      = []   # cov[c,:,:] → matriz de covariância d×d da classe c
        self.Q        = []   # Q[c,:,:]   → autovetores de cov[c] (decomposição espectral)
        self.L        = []   # L[c,:]     → autovalores de cov[c], ordenados decrescente
        self.classnum = []   # classnum[c] → rótulo numérico real da classe c (ex: 1, 2, 3)
        self.classes_ = []   # alias de classnum — parity com dzetsaka (classifyImage acessa model.classes_)
        self.tau      = 0.0  # ridge regularization — 0 = sem regularização (padrão dzetsaka)

    def learn(self, x, y):
        # QUANDO É CHAMADO: chamado uma vez em _train_gmm() após extrair as amostras.
        # x: array (n_amostras, n_bandas) com os valores de pixel normalizados [-1, 1]
        # y: array (n_amostras,) com os rótulos de classe (inteiros 1, 2, 3…)
        from numpy import linalg as _la
        C = np.unique(y).shape[0]       # número de classes distintas
        n, d = x.shape[0], x.shape[1]  # n=amostras, d=dimensões (bandas)

        # Pré-aloca os arrays com as dimensões certas antes do loop — mais eficiente
        # do que concatenar arrays a cada iteração (que criaria cópias em memória).
        self.ni       = np.empty((C, 1))
        self.prop     = np.empty((C, 1))
        self.mean     = np.empty((C, d))
        self.cov      = np.empty((C, d, d))
        self.Q        = np.empty((C, d, d))
        self.L        = np.empty((C, d))
        self.classnum = np.empty(C, dtype=np.uint16)
        self.classes_ = self.classnum   # alias — atualiza automaticamente conforme classnum é preenchido

        for c, cR in enumerate(np.unique(y)):
            # j → índices das linhas de x que pertencem à classe cR
            j = np.where(y == cR)[0]
            self.classnum[c]      = cR
            self.ni[c]            = float(j.size)
            self.prop[c]          = self.ni[c] / n

            # Média e covariância da distribuição gaussiana desta classe.
            # bias=1 → divide por N (MLE), não N-1 (como no dzetsaka original).
            # rowvar=0 → cada coluna é uma variável (banda), cada linha uma amostra.
            # Aviso: com j.size < d+1 amostras, a covariância d×d tem rank deficiente
            # (autovalores ≈ 0). O piso em _compute_inverse_logdet evita NaN, mas
            # a covariância estimada é ruim — adicione mais amostras desta classe.
            self.mean[c, :]       = np.mean(x[j, :], axis=0)
            self.cov[c, :, :]     = np.cov(x[j, :], bias=1, rowvar=0)

            # Decomposição espectral da covariância: cov = Q * diag(L) * Q^T
            # eigh (não eig) porque a covariância é simétrica — eigh é mais
            # estável numericamente e garante autovalores reais.
            # Os autovalores L são ordenados de forma decrescente para consistência
            # com a inversão via ridge: L[0] > L[1] > … > L[d-1].
            L, Q = _la.eigh(self.cov[c, :, :])
            idx = L.argsort()[::-1]
            self.L[c, :]    = L[idx]
            self.Q[c, :, :] = Q[:, idx]

    def predict(self, xt, tau=None):
        # QUANDO É CHAMADO: chamado por _predict_blocks() para classificar cada bloco.
        # xt: array (n_pixels, n_bandas) com os pixels do bloco, normalizados [-1, 1].
        # Retorna: array (n_pixels,) com os rótulos de classe preditos (inteiros).
        nt  = xt.shape[0]
        C   = self.ni.shape[0]
        K   = np.empty((nt, C))     # K[i, c] = "custo" do pixel i pertencer à classe c
        TAU = self.tau if tau is None else tau

        for c in range(C):
            invCov, logdet = self._compute_inverse_logdet(c, TAU)

            # Critério de decisão bayesiano:
            # K[i,c] = distância de Mahalanobis(pixel_i, classe_c)^2
            #         + log(det(Σ_c)) - 2*log(p(c))
            # Minimizar K equivale a maximizar a probabilidade a posteriori.
            cst             = logdet - 2 * np.log(self.prop[c])
            xtc             = xt - self.mean[c, :]             # centraliza em relação à média
            temp            = np.dot(invCov, xtc.T).T          # aplica covariância inversa
            K[:, c]         = np.sum(xtc * temp, axis=1) + cst

        # argmin(K) → índice da classe com menor custo → classe mais provável
        yp = np.argmin(K, 1)
        return self.classnum[yp]   # converte índice interno → rótulo real (1, 2, 3…)

    def _compute_inverse_logdet(self, c, tau):
        # Calcula a inversa da covariância regularizada e seu log-determinante
        # usando a decomposição espectral já computada em learn().
        #
        # cov_c^{-1} = Q * diag(1 / (L + tau)) * Q^T
        # log|cov_c| = sum(log(L + tau))
        #
        # tau (ridge) é somado ANTES da inversão: sem ele, autovalores próximos
        # de zero causariam divisão por valores minúsculos → instabilidade numérica.
        #
        # np.maximum(..., eps): piso mínimo nos autovalores APÓS somar tau.
        # Sem isso, classes com poucas amostras produzem cov ≈ 0 → Lr ≈ 0 →
        # log(0) = -inf e 1/0 = inf → K = NaN → argmin(NaN) devolve índice 0,
        # fazendo todos os pixels caírem na primeira classe.
        # eps = 1e-8: grande o suficiente para evitar overflow/NaN,
        # pequeno o suficiente para não distorcer classes com covariância bem condicionada.
        # Nota: np.finfo(float64).eps (~2e-16) é pequeno demais — 1/eps = 4.5e15
        # torna o log-determinante tão negativo que a classe degenerada SEMPRE vence
        # no argmin, que é o comportamento errado. 1e-8 equilibra estabilidade e fidelidade.
        eps    = 1e-8
        Lr     = np.maximum(self.L[c, :] + tau, eps)  # autovalores regularizados c/ piso
        temp   = self.Q[c, :, :] * (1.0 / Lr)         # Q * diag(1/Lr) — broadcasting linha a linha
        invCov = np.dot(temp, self.Q[c, :, :].T)
        logdet = np.sum(np.log(Lr))
        return invCov, logdet


# ── Funções de processamento (adaptadas de dzetsaka) ─────────────────────────

def _rasterize_samples(raster_path, vector_path, field):
    """Rasteriza camada vetorial de amostras no mesmo grid do raster de entrada /
    Rasterize sample vector layer onto the same grid as the input raster.

    "Rasterizar" significa converter polígonos vetoriais em pixels de um raster.
    Cada pixel dentro de um polígono de amostra recebe o valor numérico do campo
    de classe (field). Pixels fora do extent do raster são automaticamente ignorados
    pelo GDAL (sem necessidade de recortar antes).

    Reprojeção automática: se o vetor estiver em CRS diferente do raster, esta função
    reprojecta as feições para o CRS do raster em memória (sem criar arquivo em disco)
    antes de rasterizar. Apenas as feições dentro do bbox do raster são processadas
    (filtro espacial), tornando a operação rápida mesmo para camadas de amostras grandes.
    Auto-reprojection: if vector CRS differs from raster CRS, features are reprojected
    in-memory before rasterizing. Spatial filter limits processing to raster extent only.
    """
    from osgeo import osr as _osr

    src = gdal.Open(raster_path, gdal.GA_ReadOnly)
    gt  = src.GetGeoTransform()
    nc, nl = src.RasterXSize, src.RasterYSize

    # CRS do raster em SpatialReference — SetAxisMappingStrategy garante
    # que a ordem (X, Y) = (longitude, latitude) é usada em todas as versões do GDAL 3.x.
    raster_srs = _osr.SpatialReference()
    raster_srs.ImportFromWkt(src.GetProjection())
    raster_srs.SetAxisMappingStrategy(_osr.OAMS_TRADITIONAL_GIS_ORDER)

    shp = ogr.Open(vector_path)
    lyr = shp.GetLayer()
    vec_srs = lyr.GetSpatialRef()

    # Detecta se há incompatibilidade de CRS entre vetor e raster.
    need_reproject = False
    if vec_srs is not None:
        vec_srs = vec_srs.Clone()   # clone para não modificar o SRS original
        vec_srs.SetAxisMappingStrategy(_osr.OAMS_TRADITIONAL_GIS_ORDER)
        need_reproject = not raster_srs.IsSame(vec_srs)

    if need_reproject:
        # Filtro espacial: converte o bbox do raster para o CRS do vetor
        # e aplica SetSpatialFilterRect para pular feições completamente fora.
        # Sem isso, uma camada grande seria iterada inteiramente — lento.
        # Spatial filter: convert raster bbox to vector CRS to skip non-overlapping features.
        x0 = gt[0]
        x1 = gt[0] + nc * gt[1]
        y0 = gt[3]
        y1 = gt[3] + nl * gt[5]
        xmin_r, xmax_r = min(x0, x1), max(x0, x1)
        ymin_r, ymax_r = min(y0, y1), max(y0, y1)

        try:
            t_inv = _osr.CoordinateTransformation(raster_srs, vec_srs)
            corners = [t_inv.TransformPoint(x, y)[:2]
                       for x, y in [(xmin_r, ymin_r), (xmin_r, ymax_r),
                                    (xmax_r, ymin_r), (xmax_r, ymax_r)]]
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            lyr.SetSpatialFilterRect(min(xs), min(ys), max(xs), max(ys))
        except Exception:
            pass   # filtro espacial é otimização, não blocante / spatial filter is optimization only

        # Cria um layer OGR em memória com as feições reprojetadas para o CRS do raster.
        # ogr.GetDriverByName('Memory') cria um datasource que existe só na RAM —
        # zero escrita em disco, imediato, sem artefatos em caso de erro.
        t_fwd   = _osr.CoordinateTransformation(vec_srs, raster_srs)
        mem_drv = ogr.GetDriverByName('Memory')
        mem_ds  = mem_drv.CreateDataSource('memdata')
        mem_lyr = mem_ds.CreateLayer('repr', srs=raster_srs, geom_type=lyr.GetGeomType())

        # Copia todas as definições de campo para que o campo de classes exista no layer reprojetado.
        lyr_defn = lyr.GetLayerDefn()
        for i in range(lyr_defn.GetFieldCount()):
            mem_lyr.CreateField(lyr_defn.GetFieldDefn(i))

        for feat in lyr:
            geom = feat.GetGeometryRef()
            if geom is None:
                continue
            geom = geom.Clone()
            if geom.Transform(t_fwd) != 0:
                continue   # transformação falhou para esta feição — ignora
            new_feat = ogr.Feature(mem_lyr.GetLayerDefn())
            new_feat.SetGeometry(geom)
            for i in range(lyr_defn.GetFieldCount()):
                new_feat.SetField(i, feat.GetField(i))
            mem_lyr.CreateFeature(new_feat)

        burn_lyr = mem_lyr
        burn_ds  = mem_ds   # manter referência viva até o fim da função
    else:
        burn_lyr = lyr
        burn_ds  = shp   # manter referência viva

    # Cria o raster de saída com EXATAMENTE as mesmas dimensões e geotransform
    # do raster de entrada. GDT_UInt16 suporta até 65535 classes — suficiente.
    tmp    = tempfile.mktemp(suffix='.tif')
    driver = gdal.GetDriverByName('GTiff')
    dst    = driver.Create(tmp, nc, nl, 1, gdal.GDT_UInt16)
    dst.SetGeoTransform(gt)
    dst.SetProjection(src.GetProjection())

    # Inicializa TODOS os pixels com _ROI_NODATA (65535) ANTES de rasterizar.
    # Sem isso, pixels fora de qualquer polígono teriam valor 0 — o padrão do GDAL —
    # e classe 0 seria indistinguível de "sem amostra". Fill() + SetNoDataValue()
    # garantem que só pixels DENTRO de polígonos têm valor de classe real (0, 1, 2…).
    # Initialize ALL pixels with _ROI_NODATA before rasterizing so class 0 is valid.
    _b = dst.GetRasterBand(1)
    _b.Fill(_ROI_NODATA)
    _b.SetNoDataValue(_ROI_NODATA)
    _b = None

    # ATTRIBUTE=field: usa o valor numérico do campo de classe de cada feição
    # como valor de pixel — classe 0 → pixel=0, classe 1 → pixel=1, etc.
    gdal.RasterizeLayer(dst, [1], burn_lyr, None, options=['ATTRIBUTE=' + field])

    # Fechar todos os handles GDAL/OGR (equivale a fclose() em C).
    # Sem isso o arquivo temporário pode ficar bloqueado no Windows.
    src = dst = shp = lyr = burn_lyr = burn_ds = None
    return tmp


def _get_samples(raster_path, roi_path):
    """Extrai pixels de treinamento bloco a bloco / Extract training pixels block by block.

    Lê os dois rasters (imagem e ROI de amostras) em blocos sincronizados
    para não carregar a imagem inteira na RAM de uma vez. Para cada pixel
    onde o ROI tem valor > 0, extrai os valores de todas as bandas da imagem.

    :returns: (X, Y)
        X: (n_amostras, n_bandas) float64 — valores espectrais dos pixels de amostra
        Y: (n_amostras,) uint16           — rótulo de classe correspondente
    """
    raster = gdal.Open(raster_path, gdal.GA_ReadOnly)
    roi    = gdal.Open(roi_path,    gdal.GA_ReadOnly)

    d  = raster.RasterCount   # número de bandas (ex: 4 para RGBN)
    nc = raster.RasterXSize   # largura em pixels
    nl = raster.RasterYSize   # altura em pixels

    # GetBlockSize() retorna o tamanho do bloco interno do GeoTIFF (TILE_WIDTH, TILE_HEIGHT).
    # Ler exatamente no tamanho de bloco nativo é o mais eficiente — evita I/O extra.
    # Para rasters não tileados, block_x = largura total, block_y = 1 (strip por linha).
    block_x = raster.GetRasterBand(1).GetBlockSize()[0]
    block_y = raster.GetRasterBand(1).GetBlockSize()[1]

    X = np.empty((0, d), dtype=np.float64)
    Y = np.empty((0,),   dtype=np.uint16)

    for i in range(0, nl, block_y):
        lines = min(block_y, nl - i)   # evita ler além do limite inferior da imagem
        for j in range(0, nc, block_x):
            cols = min(block_x, nc - j)

            # mask → array 2D do bloco do ROI.
            # Pixels com amostra têm valor de classe (0, 1, 2…); pixels sem amostra = _ROI_NODATA.
            # NÃO usamos np.nonzero porque isso excluiria a classe 0 como se fosse "sem amostra".
            # Em vez disso, filtramos explicitamente pelo sentinela _ROI_NODATA.
            mask = roi.GetRasterBand(1).ReadAsArray(j, i, cols, lines)
            t = np.where(mask != _ROI_NODATA)   # t = (linhas, colunas) dos pixels com amostra
            if t[0].size == 0:
                continue   # bloco sem nenhuma amostra — pula

            # Extrai os valores de pixel de cada banda para os pixels de amostra.
            # band[t] usa indexação fancy numpy: seleciona só os pixels em t.
            Xb = np.empty((t[0].size, d), dtype=np.float64)
            for k in range(d):
                band = raster.GetRasterBand(k + 1).ReadAsArray(j, i, cols, lines)
                Xb[:, k] = band[t].astype(np.float64)

            X = np.concatenate((X, Xb))
            Y = np.concatenate((Y, mask[t].astype(np.uint16)))

    raster = roi = None   # fecha os handles GDAL
    return X, Y


def _predict_blocks(raster_path, out_path, predict_fn, scale_params, nodata=_ROI_NODATA, progress_cb=None, interrupt_check=None):
    """Classifica o raster inteiro bloco a bloco / Classify the full raster block by block.

    A abordagem por blocos é fundamental: imagens de drone podem ter gigabytes.
    Carregar tudo na RAM de uma vez causaria MemoryError. Ao processar bloco
    a bloco no mesmo tamanho de tile do arquivo, o uso de RAM fica constante
    independente do tamanho da imagem.

    :param predict_fn:   callable(X_block: ndarray) → ndarray com rótulos de classe
    :param scale_params: (M, m) para normalização [-1, 1] — deve ser o mesmo M, m
                         usado no treinamento, caso contrário os valores de entrada
                         estariam em escala diferente dos dados que o modelo viu
    :param progress_cb:  callable(int 0-100) ou None — emite progresso para a UI
    """
    raster = gdal.Open(raster_path, gdal.GA_ReadOnly)
    d  = raster.RasterCount
    nc = raster.RasterXSize
    nl = raster.RasterYSize

    gt  = raster.GetGeoTransform()   # georreferenciamento (origem, resolução, rotação)
    prj = raster.GetProjection()     # sistema de coordenadas em formato WKT

    block_x = raster.GetRasterBand(1).GetBlockSize()[0]
    block_y = raster.GetRasterBand(1).GetBlockSize()[1]
    nodata_val = raster.GetRasterBand(1).GetNoDataValue()
    if nodata_val is None:
        nodata_val = -9999.0   # valor sentinela impossível → classifica todos os pixels

    # No Windows, se o arquivo de saída já estiver carregado no QGIS como camada,
    # o handle do arquivo fica aberto e o GDAL não consegue deletá-lo antes de recriar.
    # Tentamos remover antes para dar uma mensagem de erro clara ao usuário.
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            raise OSError(
                'O arquivo de saída já existe e está sendo usado pelo QGIS (handle aberto):\n'
                '{}\n\n'
                'Soluções:\n'
                '  • Remova a camada de classificação anterior do painel de camadas e tente de novo.\n'
                '  • Ou escolha um caminho de saída diferente.\n\n'
                'Output file already exists and is locked by QGIS (open handle):\n'
                '{}\n\n'
                'Solutions:\n'
                '  • Remove the previous classification layer from the layer panel and retry.\n'
                '  • Or choose a different output path.'.format(out_path, out_path))

    driver = gdal.GetDriverByName('GTiff')
    # COMPRESS=LZW → compressão sem perdas que reduz o arquivo ~50-70% para rasters
    # de classificação (poucos valores únicos = alta compressibilidade).
    # TILED=YES    → salva em tiles 256×256 em vez de strip por linha; necessário
    # para que o QGIS possa ler áreas arbitrárias sem ler o arquivo inteiro.
    # BIGTIFF=IF_SAFER → permite arquivos > 4 GB se necessário.
    dst = driver.Create(out_path, nc, nl, 1, gdal.GDT_UInt16,
                        options=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER'])
    dst.SetGeoTransform(gt)
    dst.SetProjection(prj)
    out_band = dst.GetRasterBand(1)
    out_band.SetNoDataValue(nodata)   # pixels sem dado serão marcados com 0

    total_blocks = (nl // block_y + 1) * (nc // block_x + 1)
    done = 0

    M, m = scale_params if scale_params is not None else (None, None)

    for i in range(0, nl, block_y):
        if interrupt_check and interrupt_check():
            out_band = dst = raster = None   # fecha handles antes de sair
            return False
        lines = min(block_y, nl - i)
        for j in range(0, nc, block_x):
            cols = min(block_x, nc - j)

            # Monta o array do bloco: cols*lines linhas, d colunas (uma por banda)
            X = np.empty((cols * lines, d), dtype=np.float64)
            for k in range(d):
                X[:, k] = raster.GetRasterBand(k + 1).ReadAsArray(
                    j, i, cols, lines).reshape(cols * lines).astype(np.float64)

            # Identifica pixels válidos (sem nodata) para não classificar bordas/água.
            valid = np.where(X[:, 0] != nodata_val)[0]
            # Inicializa com `nodata` (65535 por padrão) em vez de 0, para que pixels
            # fora do extent do raster não sejam confundidos com a classe 0.
            yp = np.full(cols * lines, nodata, dtype=np.uint16)

            if valid.size > 0:
                Xv = X[valid]
                if M is not None:
                    # Aplica a mesma normalização [-1, 1] usada no treinamento.
                    # Se den==0 (banda constante), coloca 0 para não dividir por zero.
                    den = M - m
                    Xs = np.where(den != 0, 2.0 * (Xv - m) / den - 1.0, 0.0)
                else:
                    Xs = Xv
                yp[valid] = predict_fn(Xs).astype(np.uint16)

            # Grava o bloco classificado no GeoTIFF de saída.
            # FlushCache() força a escrita em disco — sem isso, dados podem ficar
            # no buffer e o arquivo ficaria corrompido se o processo morrer.
            out_band.WriteArray(yp.reshape(lines, cols), j, i)
            out_band.FlushCache()

            done += 1
            if progress_cb:
                progress_cb(int(done / total_blocks * 100))

    out_band = dst = raster = None   # fecha e salva o arquivo GeoTIFF
    return True


# ── Worker (QThread) ──────────────────────────────────────────────────────────

class _MLWorker(QThread):
    # Todo processamento pesado (I/O de raster, treino de modelo, classificação)
    # roda aqui, fora da thread principal do QGIS. Se rodasse na thread principal,
    # o QGIS ficaria congelado durante a classificação — às vezes por vários minutos
    # em imagens grandes. Com QThread, o usuário pode até fechar o diálogo.
    #
    # Comunicação com a UI: via pyqtSignal. A UI conecta os sinais a slots
    # (ex: progress → QProgressBar.setValue) em _on_run(). Quando o worker
    # emite um sinal, o Qt entrega na thread principal de forma segura.
    """Executa treinamento e classificação fora da thread principal /
    Runs training and classification outside the main thread."""

    progress  = pyqtSignal(int)    # int 0–100 → atualiza a barra de progresso
    status    = pyqtSignal(str)    # string → atualiza o label de status na UI
    finished  = pyqtSignal(str)    # caminho do raster classificado → carrega no QGIS
    error     = pyqtSignal(str)    # mensagem de erro → mostra na messageBar
    cancelled = pyqtSignal()       # emitido quando o usuário clica em Cancelar
    # diag: mensagem de diagnóstico importante (ex: distribuição de classes) que não deve
    # ser sobrescrita pelo próximo status — é empurrada para a messageBar do QGIS,
    # que persiste até o usuário fechar, mesmo enquanto o label de status muda.
    diag      = pyqtSignal(str)

    def __init__(self, raster_path, vector_path, field, model_key, model_params,
                 out_path, split_pct, save_matrix, parent=None):
        super().__init__(parent)
        self._raster_path  = raster_path
        self._vector_path  = vector_path
        self._field        = field
        self._model_key    = model_key      # 'RF' ou 'GMM'
        self._model_params = model_params   # dict com n_estimators, max_depth (RF) ou {} (GMM)
        self._out_path     = out_path
        self._split_pct    = split_pct      # int 0–100 = % treino, ou None para sem split
        self._save_matrix  = save_matrix    # bool: salvar matriz de confusão em CSV?

    def run(self):
        # QUANDO É CHAMADO: Qt chama run() automaticamente ao chamar .start() na thread.
        # O try/except aqui é a rede de segurança: qualquer exceção não tratada
        # em _execute() emite o sinal de erro para a UI em vez de silenciosamente
        # terminar a thread sem feedback para o usuário.
        try:
            self._execute()
        except Exception as exc:
            self.error.emit(str(exc))

    def _execute(self):
        # 1 — Rasteriza amostras (com reprojeção automática se CRS diferente)
        self.status.emit(
            'Rasterizando amostras (reprojeção automática se CRS diferente)... / '
            'Rasterizing samples (auto-reprojection if CRS differs)...')
        self.progress.emit(5)
        roi_path = _rasterize_samples(self._raster_path, self._vector_path, self._field)

        # 2 — Extrai pixels de treinamento
        self.status.emit('Extraindo pixels de treinamento... / Extracting training pixels...')
        self.progress.emit(15)
        X, Y = _get_samples(self._raster_path, roi_path)
        try:
            os.remove(roi_path)
        except OSError:
            pass

        if X.size == 0:
            raise ValueError(
                'Nenhuma amostra encontrada. Verifique o campo de classes e a sobreposição.\n'
                'Causas comuns: CRS da camada de amostras diferente do raster; '
                'polígonos fora da imagem; campo de classes inválido.\n'
                'No samples found. Check class field and spatial overlap.\n'
                'Common causes: sample layer CRS differs from raster; '
                'polygons outside image; invalid class field.')

        # Diagnóstico: mostra quantas amostras foram extraídas por classe.
        unique_cls, counts = np.unique(Y, return_counts=True)
        diag = '  '.join('Cls{}: {}px'.format(int(c), int(n))
                         for c, n in zip(unique_cls, counts))
        diag_msg = 'Amostras: {} pixels em {} classe(s) — {} / Samples: {} pixels in {} class(es) — {}'.format(
            int(Y.size), len(unique_cls), diag,
            int(Y.size), len(unique_cls), diag)
        self.status.emit(diag_msg)
        self.diag.emit(diag_msg)

        # Se só há 1 classe nas amostras, o modelo vai prever apenas essa classe
        # para todos os pixels — resultado inútil. Isso quase sempre significa
        # CRS incompatível, campo errado ou polígonos fora do raster.
        # If only 1 class found, model will predict that class everywhere — useless result.
        # This almost always means CRS mismatch, wrong field, or polygons outside raster.
        if len(unique_cls) < 2:
            raise ValueError(
                'Apenas 1 classe encontrada nas amostras (Cls{}). O modelo não pode aprender '
                'a distinguir classes com apenas 1 tipo de amostra.\n\n'
                'Verifique:\n'
                '  • O campo "{}" contém valores numéricos diferentes por classe?\n'
                '  • O CRS da camada de amostras é o MESMO do raster?\n'
                '  • Os polígonos de TODAS as classes sobrepõem a imagem?\n\n'
                'Only 1 class found in samples (Cls{}). The model cannot learn to\n'
                'distinguish classes with only 1 type of sample.\n\n'
                'Check:\n'
                '  • Does field "{}" have different numeric values per class?\n'
                '  • Is the sample layer CRS the SAME as the raster CRS?\n'
                '  • Do polygons for ALL classes overlap the image?'.format(
                    int(unique_cls[0]), self._field,
                    int(unique_cls[0]), self._field))

        n_classes = int(Y.max())

        # 3 — Normalização para [-1, 1] (idêntico ao dzetsaka: 2*(x-m)/(M-m) - 1)
        M = np.amax(X, axis=0)
        m = np.amin(X, axis=0)
        den = M - m
        Xs = np.where(den != 0, 2.0 * (X - m) / den - 1.0, 0.0)

        # 4 — Split amostral opcional
        x_train, y_train = Xs, Y
        x_test,  y_test  = None, None

        if self._split_pct and self._split_pct > 0:
            self.status.emit(
                'Dividindo amostras ({:.0f}% treino)... / '
                'Splitting samples ({:.0f}% train)...'.format(
                    self._split_pct, self._split_pct))
            self.progress.emit(20)
            np.random.seed(42)
            x_train = np.empty((0, Xs.shape[1]))
            y_train = np.empty((0,), dtype=np.uint16)
            x_test  = np.empty((0, Xs.shape[1]))
            y_test  = np.empty((0,), dtype=np.uint16)
            train_ratio = self._split_pct / 100.0
            for cls in np.unique(Y):   # np.unique garante que classe 0 seja incluída; range(1, n+1) a excluiria
                idx = np.where(Y == cls)[0]
                if idx.size == 0:
                    continue
                n_tr = max(1, int(idx.size * train_ratio))
                perm = np.random.permutation(idx.size)
                x_train = np.concatenate((x_train, Xs[idx[perm[:n_tr]]]))
                y_train = np.concatenate((y_train, Y[idx[perm[:n_tr]]]))
                x_test  = np.concatenate((x_test,  Xs[idx[perm[n_tr:]]]))
                y_test  = np.concatenate((y_test,  Y[idx[perm[n_tr:]]]))

        # Valida que o split não eliminou classes (pode acontecer se uma classe
        # tiver poucas amostras e o split_pct for muito alto).
        if self._split_pct and self._split_pct > 0:
            train_cls = np.unique(y_train)
            if len(train_cls) < 2:
                raise ValueError(
                    'Após o split, apenas 1 classe ficou no conjunto de treino (Cls{}).\n'
                    'Reduza o % de treino ou adicione mais amostras das classes com poucos polígonos.\n'
                    'After split, only 1 class remained in the training set (Cls{}).\n'
                    'Reduce the train % or add more polygons for under-represented classes.'.format(
                        int(train_cls[0]), int(train_cls[0])))

        # 5 — Treina o modelo
        self.status.emit('Treinando modelo {}... / Training {} model...'.format(
            self._model_key, self._model_key))
        self.progress.emit(30)

        if self._model_key == 'RF':
            model, predict_fn = self._train_rf(x_train, y_train)
        elif self._model_key == 'ET':
            model, predict_fn = self._train_et(x_train, y_train)
        elif self._model_key == 'GB':
            model, predict_fn = self._train_gb(x_train, y_train)
        elif self._model_key == 'SVM':
            model, predict_fn = self._train_svm(x_train, y_train)
        elif self._model_key == 'KNN':
            model, predict_fn = self._train_knn(x_train, y_train)
        elif self._model_key == 'NB':
            model, predict_fn = self._train_nb(x_train, y_train)
        elif self._model_key == 'GMM_SK':
            model, predict_fn = self._train_gmm_sk(x_train, y_train)
        else:   # GMM nativo
            model, predict_fn = self._train_gmm(x_train, y_train, n_classes)

        # 6 — Matriz de confusão opcional
        if self._split_pct and x_test is not None and x_test.size > 0:
            self.status.emit('Calculando matriz de confusão... / Computing confusion matrix...')
            self.progress.emit(55)
            y_pred = predict_fn(x_test)
            oa, kappa, matrix, labels = self._confusion_matrix(y_test, y_pred)
            self.status.emit(
                'OA: {:.1f}%  Kappa: {:.3f} / OA: {:.1f}%  Kappa: {:.3f}'.format(
                    oa * 100, kappa, oa * 100, kappa))

            if self._save_matrix:
                mat_path = os.path.splitext(self._out_path)[0] + '_matriz_confusao.csv'
                header = 'Classes: ' + ','.join(str(int(l)) for l in labels)
                np.savetxt(mat_path, matrix, delimiter=',', fmt='%d', header=header)
                self.status.emit(
                    'Matriz salva em {} / Matrix saved to {}'.format(
                        os.path.basename(mat_path), os.path.basename(mat_path)))

        # 7 — Classifica a imagem inteira
        self.status.emit('Classificando imagem... / Classifying image...')
        self.progress.emit(60)
        completed = _predict_blocks(
            self._raster_path, self._out_path,
            predict_fn=predict_fn,
            scale_params=(M, m),
            progress_cb=lambda v: self.progress.emit(60 + int(v * 0.35)),
            interrupt_check=lambda: self.isInterruptionRequested())

        if not completed:
            # Cancellamento pelo usuário: remove o arquivo parcial para não deixar lixo.
            try:
                os.remove(self._out_path)
            except OSError:
                pass
            self.cancelled.emit()
            return

        self.progress.emit(100)
        self.finished.emit(self._out_path)

    def _train_rf(self, X, Y):
        # Importamos sklearn aqui (não no topo do arquivo) porque é opcional —
        # o GMM funciona sem ele. Isso também permite instalar sklearn em tempo
        # de execução via _PipInstallWorker e usar na mesma sessão do QGIS.
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError:
            raise ImportError(
                'scikit-learn não encontrado. Instale via OSGeo4W Shell: '
                'pip install scikit-learn / '
                'scikit-learn not found. Install via OSGeo4W Shell: pip install scikit-learn')

        params = {}
        n_est = self._model_params.get('n_estimators', 100)
        max_d = self._model_params.get('max_depth', None)
        if n_est:
            params['n_estimators'] = int(n_est)
        if max_d:
            params['max_depth'] = int(max_d)
        # n_jobs=1 força uso de apenas 1 thread no sklearn.
        # No Windows, o multiprocessing do sklearn usa "spawn" (não "fork"),
        # o que causa problemas dentro do processo do QGIS — pode travar ou
        # lançar exceção de pickling. n_jobs=1 desativa isso completamente.
        params['n_jobs'] = 1

        Y_flat = Y.ravel()   # ravel() garante array 1D (o fit do sklearn exige)
        clf = RandomForestClassifier(**params)
        clf.fit(X, Y_flat)
        # Retornamos o objeto e seu método predict separadamente para que
        # _execute() e _predict_blocks() usem a mesma interface (callable),
        # independentemente de ser RF ou GMM.
        return clf, clf.predict

    def _train_gmm(self, X, Y, n_classes):
        # Interface simétrica ao _train_rf: retorna (modelo, callable predict).
        # _GMMR.learn() é equivalente ao clf.fit(); _GMMR.predict() ao clf.predict().
        d = X.shape[1]
        for cR in np.unique(Y):
            cnt = int(np.sum(Y == cR))
            if cnt < d + 1:
                self.status.emit(
                    'AVISO GMM: classe {} tem {} amostra(s) — recomendado >= {} para {} bandas. '
                    'Adicione mais polígonos de treinamento. / '
                    'GMM WARNING: class {} has {} sample(s) — recommended >= {} for {} bands. '
                    'Add more training polygons.'.format(
                        cR, cnt, d + 1, d, cR, cnt, d + 1, d))
        gmm = _GMMR()
        gmm.learn(X, Y)
        return gmm, gmm.predict

    def _train_et(self, X, Y):
        try:
            from sklearn.ensemble import ExtraTreesClassifier
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. Instale via o botão abaixo. / '
                              'scikit-learn not found. Install via the button below.') from e
        params = {}
        n_est = self._model_params.get('n_estimators', 100)
        max_d = self._model_params.get('max_depth', None)
        if n_est:
            params['n_estimators'] = int(n_est)
        if max_d:
            params['max_depth'] = int(max_d)
        clf = ExtraTreesClassifier(**params, n_jobs=-1, random_state=42)
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    def _train_gb(self, X, Y):
        try:
            from sklearn.ensemble import HistGradientBoostingClassifier
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. / scikit-learn not found.') from e
        max_iter = int(self._model_params.get('max_iter', 100))
        lr       = float(self._model_params.get('learning_rate', 0.1))
        clf = HistGradientBoostingClassifier(max_iter=max_iter, learning_rate=lr, random_state=42)
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    def _train_svm(self, X, Y):
        try:
            from sklearn.svm import SVC
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. / scikit-learn not found.') from e
        C = float(self._model_params.get('C', 1.0))
        clf = SVC(C=C, kernel='rbf', gamma='scale', cache_size=500, decision_function_shape='ovr')
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    def _train_knn(self, X, Y):
        try:
            from sklearn.neighbors import KNeighborsClassifier
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. / scikit-learn not found.') from e
        k = int(self._model_params.get('n_neighbors', 5))
        clf = KNeighborsClassifier(n_neighbors=k, n_jobs=-1)
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    def _train_nb(self, X, Y):
        try:
            from sklearn.naive_bayes import GaussianNB
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. / scikit-learn not found.') from e
        clf = GaussianNB()
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    def _train_gmm_sk(self, X, Y):
        try:
            from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
        except ImportError as e:
            raise ImportError('scikit-learn não encontrado. / scikit-learn not found.') from e
        reg = float(self._model_params.get('reg_param', 0.0))
        clf = QuadraticDiscriminantAnalysis(reg_param=reg)
        clf.fit(X, Y.ravel())
        return clf, clf.predict

    @staticmethod
    def _confusion_matrix(y_true, y_pred):
        # Constrói a matriz de confusão manualmente com numpy em vez de usar
        # sklearn.metrics.confusion_matrix — assim funciona sem sklearn (para GMM).
        # Linha i → classe real i; coluna j → classe predita j.
        # A diagonal principal são os acertos.
        labels = np.unique(np.concatenate((y_true, y_pred)))
        n = len(labels)
        label_to_idx = {int(l): i for i, l in enumerate(labels)}
        matrix = np.zeros((n, n), dtype=np.int64)
        for t, p in zip(y_true.ravel(), y_pred.ravel()):
            matrix[label_to_idx[int(t)], label_to_idx[int(p)]] += 1
        total   = matrix.sum()
        # OA (Overall Accuracy) = acertos totais / total de amostras de teste
        oa      = np.trace(matrix) / total if total > 0 else 0.0
        # p_e = concordância esperada ao acaso (necessário para o Kappa de Cohen)
        p_e     = sum((matrix[i, :].sum() * matrix[:, i].sum()) for i in range(n)) / (total ** 2)
        # Kappa corrige a OA pela concordância aleatória: 1.0 = perfeito, 0.0 = aleatório
        kappa   = (oa - p_e) / (1 - p_e) if (1 - p_e) != 0 else 0.0
        return oa, kappa, matrix, labels


# ── Dialog ────────────────────────────────────────────────────────────────────

class RthMLDialog(QDialog):
    # QDialog é a classe base do Qt para janelas de diálogo — janelas modais
    # ou não-modais com formulários. Diferente de QMainWindow, QDialog não tem
    # barra de menu nem barra de ferramentas; é focada em coleta de input do usuário.
    # Ao herdar de QDialog, ganhamos show(), hide(), close(), exec_() etc.
    #
    # iface: QgisInterface — o "controle remoto" do QGIS. Usado para:
    #   - acessar o mapa (iface.mapCanvas())
    #   - acessar a barra de mensagens (iface.messageBar())
    #   - adicionar camadas ao painel (via QgsProject.instance())
    #
    # O padrão aqui é "singleton de diálogo": RthMLTool cria o diálogo uma vez
    # e reutiliza — assim o usuário não perde suas seleções ao fechar e reabrir.
    """Diálogo principal de Classificação ML / Main ML Classification dialog."""

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface   = iface
        self._worker = None   # referência ao _MLWorker ativo; None quando ocioso
        self._setup_ui()
        self._populate_layers()

    def _setup_ui(self):
        # QUANDO É CHAMADO: chamado uma vez no __init__. Cria todos os widgets e
        # os conecta aos handlers (slots). Depois disso, a UI é só mostrada/escondida,
        # nunca recriada — isso economiza tempo e preserva o estado do usuário.
        self.setWindowTitle('RTH Machine Learning — Classificação de Uso do Solo / Land Use Classification')
        # Qt.Window  → janela independente com barra de título própria (não embutida no QGIS)
        # WindowMinimizeButtonHint → permite minimizar (útil durante classificações longas)
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint |
                            Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 14)

        def _row(label_text, widget):
            h = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(170)
            lbl.setStyleSheet('font-size:11px;')
            h.addWidget(lbl)
            h.addWidget(widget, 1)
            return h

        def _sep():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setStyleSheet('color:#ddd;')
            return line

        # ── Entradas principais ───────────────────────────────────────────────
        self._combo_raster = QComboBox()
        self._combo_raster.setStyleSheet('font-size:11px;')
        root.addLayout(_row('Imagem Raster / Raster Image:', self._combo_raster))

        self._combo_vector = QComboBox()
        self._combo_vector.setStyleSheet('font-size:11px;')
        self._combo_vector.currentIndexChanged.connect(self._on_vector_changed)
        root.addLayout(_row('Amostras Vetoriais / Sample Layer:', self._combo_vector))

        self._combo_field = QComboBox()
        self._combo_field.setStyleSheet('font-size:11px;')
        root.addLayout(_row('Campo de Classes / Class Field:', self._combo_field))

        root.addWidget(_sep())

        self._combo_model = QComboBox()
        self._combo_model.setStyleSheet('font-size:11px;')
        self._combo_model.addItem('Random Forest', 'RF')
        self._combo_model.addItem('Extra Trees', 'ET')
        self._combo_model.addItem('Gradient Boosting', 'GB')
        self._combo_model.addItem('SVM (kernel RBF)', 'SVM')
        self._combo_model.addItem('K-Nearest Neighbors', 'KNN')
        self._combo_model.addItem('Naive Bayes', 'NB')
        self._combo_model.addItem('GMM Nativo / Native (sem sklearn / without sklearn)', 'GMM')
        self._combo_model.addItem('GMM sklearn (QDA)', 'GMM_SK')
        self._combo_model.currentIndexChanged.connect(self._on_model_changed)
        root.addLayout(_row('Modelo / Model:', self._combo_model))

        def _hint(text):
            lbl = QLabel(text)
            lbl.setStyleSheet('font-size:9px; color:#888; font-style:italic; padding-left:4px;')
            lbl.setWordWrap(True)
            return lbl

        # ── Parâmetros RF ─────────────────────────────────────────────────────
        self._group_rf = QGroupBox('Parâmetros Random Forest / Random Forest Parameters')
        self._group_rf.setStyleSheet('font-size:11px;')
        grf = QVBoxLayout(self._group_rf)
        grf.setSpacing(4)

        self._spin_n_est = QSpinBox()
        self._spin_n_est.setRange(1, 2000)
        self._spin_n_est.setValue(100)
        self._spin_n_est.setStyleSheet('font-size:11px;')
        grf.addLayout(_row('Nº Árvores / n_estimators:', self._spin_n_est))
        grf.addWidget(_hint(
            '↑ Aumentar → mais preciso e estável, porém mais lento e usa mais memória. '
            'Para imagens grandes, 50–100 já costuma ser suficiente. '
            '/ ↑ Increase → more accurate and stable, but slower and uses more memory. '
            'For large images, 50–100 is usually enough.'))

        self._spin_max_depth = QSpinBox()
        self._spin_max_depth.setRange(0, 200)
        self._spin_max_depth.setValue(0)
        self._spin_max_depth.setSpecialValueText('0 = Auto (ilimitado / unlimited)')
        self._spin_max_depth.setStyleSheet('font-size:11px;')
        grf.addLayout(_row('Prof. Máxima / max_depth:', self._spin_max_depth))
        grf.addWidget(_hint(
            '0 = sem limite (árvores crescem totalmente). '
            '↑ Limitar (ex: 10–20) reduz overfitting quando há poucas amostras por classe. '
            '/ 0 = no limit (trees grow fully). '
            '↑ Limiting (e.g. 10–20) reduces overfitting when samples per class are few.'))

        root.addWidget(self._group_rf)

        # ── Parâmetros GMM ────────────────────────────────────────────────────
        self._group_gmm = QGroupBox('GMM — Classificação por Mistura Gaussiana / Gaussian Mixture Model')
        self._group_gmm.setStyleSheet('font-size:11px;')
        ggmm = QVBoxLayout(self._group_gmm)
        ggmm.setSpacing(4)

        ggmm.addWidget(_hint(
            'Gaussian Mixture Model com regularização Ridge (GMMR): '
            'decomposição espectral da covariância por classe. '
            'Usa apenas numpy — não requer nenhum pacote adicional. '
            '/ Gaussian Mixture Model with Ridge regularization (GMMR): '
            'spectral covariance decomposition per class. '
            'Uses only numpy — no additional package required.'))

        self._combo_cov = QComboBox()   # reservado para futura expansão / kept for future expansion
        self._combo_cov.setVisible(False)

        self._group_gmm.setVisible(False)
        root.addWidget(self._group_gmm)

        # ── Parâmetros GMM sklearn (QDA) ──────────────────────────────────────
        self._group_gmm_sk = QGroupBox('GMM sklearn — QuadraticDiscriminantAnalysis')
        self._group_gmm_sk.setStyleSheet('font-size:11px;')
        ggmm_sk = QVBoxLayout(self._group_gmm_sk)
        ggmm_sk.setSpacing(4)

        self._spin_qda_reg = QDoubleSpinBox()
        self._spin_qda_reg.setRange(0.0, 1.0)
        self._spin_qda_reg.setSingleStep(0.01)
        self._spin_qda_reg.setDecimals(3)
        self._spin_qda_reg.setValue(0.0)
        self._spin_qda_reg.setStyleSheet('font-size:11px;')
        ggmm_sk.addLayout(_row('Regularização / reg_param:', self._spin_qda_reg))
        ggmm_sk.addWidget(_hint(
            'Equivalente matemático ao GMM Nativo, com regularização do sklearn. '
            '0.0 = sem regularização (idêntico ao GMM Nativo). '
            '↑ Aumentar → mais estável com poucas amostras por classe, menos fiel à covariância real. '
            '/ Mathematically equivalent to Native GMM, with sklearn regularization. '
            '0.0 = no regularization (identical to Native GMM). '
            '↑ Increase → more stable with few samples per class, less faithful to true covariance.'))

        self._group_gmm_sk.setVisible(False)
        root.addWidget(self._group_gmm_sk)

        # ── Parâmetros Extra Trees ─────────────────────────────────────────────
        self._group_et = QGroupBox('Parâmetros Extra Trees / Extra Trees Parameters')
        self._group_et.setStyleSheet('font-size:11px;')
        get = QVBoxLayout(self._group_et)
        get.setSpacing(4)

        self._spin_et_n_est = QSpinBox()
        self._spin_et_n_est.setRange(1, 2000)
        self._spin_et_n_est.setValue(100)
        self._spin_et_n_est.setStyleSheet('font-size:11px;')
        get.addLayout(_row('Nº Árvores / n_estimators:', self._spin_et_n_est))

        self._spin_et_depth = QSpinBox()
        self._spin_et_depth.setRange(0, 200)
        self._spin_et_depth.setValue(0)
        self._spin_et_depth.setSpecialValueText('0 = Auto (ilimitado / unlimited)')
        self._spin_et_depth.setStyleSheet('font-size:11px;')
        get.addLayout(_row('Prof. Máxima / max_depth:', self._spin_et_depth))
        get.addWidget(_hint(
            'Similar ao Random Forest, porém os thresholds de divisão das árvores são aleatórios '
            '(não ótimos), tornando o treinamento 2–5× mais rápido com acurácia comparável. '
            '/ Similar to Random Forest, but split thresholds are random (not optimal), making '
            'training 2–5× faster with comparable accuracy.'))

        self._group_et.setVisible(False)
        root.addWidget(self._group_et)

        # ── Parâmetros SVM ────────────────────────────────────────────────────
        self._group_svm = QGroupBox('Parâmetros SVM (kernel RBF) / SVM Parameters (RBF kernel)')
        self._group_svm.setStyleSheet('font-size:11px;')
        gsvm = QVBoxLayout(self._group_svm)
        gsvm.setSpacing(4)

        self._spin_svm_c = QDoubleSpinBox()
        self._spin_svm_c.setRange(0.001, 10000.0)
        self._spin_svm_c.setSingleStep(0.5)
        self._spin_svm_c.setDecimals(3)
        self._spin_svm_c.setValue(1.0)
        self._spin_svm_c.setStyleSheet('font-size:11px;')
        gsvm.addLayout(_row('Penalidade / C:', self._spin_svm_c))
        gsvm.addWidget(_hint(
            'C controla o balanço entre margem máxima e erros de classificação. '
            '↓ Menor C → margem maior, mais erros tolerados (melhor generalização). '
            '↑ Maior C → fronteira mais rígida, possível overfitting. '
            'Kernel RBF fixo — padrão-ouro para dados espectrais multibanda. '
            '/ C controls the trade-off between maximum margin and misclassifications. '
            '↓ Smaller C → wider margin, more tolerance for errors (better generalization). '
            '↑ Larger C → tighter boundary, possible overfitting. '
            'RBF kernel fixed — gold standard for multispectral data.'))

        self._group_svm.setVisible(False)
        root.addWidget(self._group_svm)

        # ── Parâmetros KNN ────────────────────────────────────────────────────
        self._group_knn = QGroupBox('Parâmetros / Parameters K-Nearest Neighbors')
        self._group_knn.setStyleSheet('font-size:11px;')
        gknn = QVBoxLayout(self._group_knn)
        gknn.setSpacing(4)

        self._spin_knn_k = QSpinBox()
        self._spin_knn_k.setRange(1, 50)
        self._spin_knn_k.setValue(5)
        self._spin_knn_k.setStyleSheet('font-size:11px;')
        gknn.addLayout(_row('Nº Vizinhos / n_neighbors:', self._spin_knn_k))
        gknn.addWidget(_hint(
            'Classifica cada pixel com base nos K vizinhos mais próximos no espaço espectral. '
            '↓ K=1 → mais sensível a ruído. ↑ K grande → fronteiras mais suaves, menos detalhes. '
            '5–9 é um bom ponto de partida. '
            '/ Classifies each pixel based on its K nearest neighbors in spectral space. '
            '↓ K=1 → sensitive to noise. ↑ Large K → smoother boundaries, less detail. '
            '5–9 is a good starting point.'))

        self._group_knn.setVisible(False)
        root.addWidget(self._group_knn)

        # ── Parâmetros Naive Bayes ────────────────────────────────────────────
        self._group_nb = QGroupBox('Naive Bayes Gaussiano / Gaussian Naive Bayes')
        self._group_nb.setStyleSheet('font-size:11px;')
        gnb = QVBoxLayout(self._group_nb)
        gnb.setSpacing(4)
        gnb.addWidget(_hint(
            'GaussianNB — modelo probabilístico extremamente rápido que assume independência '
            'entre bandas (covariância diagonal). Útil como baseline rápido para comparação. '
            'Não requer ajuste de parâmetros. '
            '/ GaussianNB — extremely fast probabilistic model that assumes band independence '
            '(diagonal covariance). Useful as a quick baseline for comparison. No parameter tuning needed.'))

        self._group_nb.setVisible(False)
        root.addWidget(self._group_nb)

        # ── Parâmetros Gradient Boosting ──────────────────────────────────────
        self._group_gb = QGroupBox('Parâmetros Gradient Boosting / Gradient Boosting Parameters')
        self._group_gb.setStyleSheet('font-size:11px;')
        ggb = QVBoxLayout(self._group_gb)
        ggb.setSpacing(4)

        self._spin_gb_iter = QSpinBox()
        self._spin_gb_iter.setRange(10, 2000)
        self._spin_gb_iter.setValue(100)
        self._spin_gb_iter.setStyleSheet('font-size:11px;')
        ggb.addLayout(_row('Nº Iterações / max_iter:', self._spin_gb_iter))
        ggb.addWidget(_hint(
            '↑ Mais iterações → melhor acurácia, porém mais lento. '
            '100–200 é suficiente para a maioria dos casos. '
            '/ ↑ More iterations → better accuracy, but slower. '
            '100–200 is enough for most cases.'))

        self._spin_gb_lr = QDoubleSpinBox()
        self._spin_gb_lr.setRange(0.001, 1.0)
        self._spin_gb_lr.setSingleStep(0.01)
        self._spin_gb_lr.setDecimals(3)
        self._spin_gb_lr.setValue(0.1)
        self._spin_gb_lr.setStyleSheet('font-size:11px;')
        ggb.addLayout(_row('Taxa de Aprendizado / learning_rate:', self._spin_gb_lr))
        ggb.addWidget(_hint(
            '↓ Menor taxa → mais iterações necessárias, menor risco de overfitting. '
            '↑ Maior taxa → treino mais rápido, mais instável. '
            '0.05–0.1 é recomendado. '
            '/ ↓ Smaller rate → more iterations needed, lower overfitting risk. '
            '↑ Larger rate → faster training, more instability. 0.05–0.1 is recommended.'))

        self._group_gb.setVisible(False)
        root.addWidget(self._group_gb)

        root.addWidget(_sep())

        # ── Saída ─────────────────────────────────────────────────────────────
        row_out = QHBoxLayout()
        lbl_out = QLabel('Raster de Saída / Output Raster:')
        lbl_out.setFixedWidth(170)
        lbl_out.setStyleSheet('font-size:11px;')
        row_out.addWidget(lbl_out)
        self._edit_out = QLineEdit()
        self._edit_out.setStyleSheet('font-size:11px;')
        self._edit_out.setPlaceholderText('Caminho do arquivo de saída... / Output file path...')
        self._edit_out.textChanged.connect(self._on_out_path_changed)
        row_out.addWidget(self._edit_out, 1)
        btn_browse = QPushButton('📁')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._on_browse_out)
        row_out.addWidget(btn_browse)
        root.addLayout(row_out)

        root.addWidget(_sep())

        # ── Opcionais ─────────────────────────────────────────────────────────
        self._chk_matrix = QCheckBox(
            'Salvar Matriz de Confusão (.csv) / Save Confusion Matrix (.csv)')
        self._chk_matrix.setStyleSheet('font-size:11px;')
        self._chk_matrix.setEnabled(False)
        root.addWidget(self._chk_matrix)

        row_split = QHBoxLayout()
        self._chk_split = QCheckBox('Split Amostral para Validação / Sample Split for Validation:')
        self._chk_split.setStyleSheet('font-size:11px;')
        self._chk_split.stateChanged.connect(self._on_split_toggled)
        row_split.addWidget(self._chk_split)
        self._spin_split = QSpinBox()
        self._spin_split.setRange(0, 100)
        self._spin_split.setValue(70)
        self._spin_split.setSuffix('%  (treino / train)')
        self._spin_split.setStyleSheet('font-size:11px;')
        self._spin_split.setEnabled(False)
        row_split.addWidget(self._spin_split)
        row_split.addStretch()
        root.addLayout(row_split)

        # ── Progress + status ─────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setStyleSheet('font-size:10px;')
        root.addWidget(self._progress)

        self._lbl_status = QLabel('')
        self._lbl_status.setStyleSheet('font-size:13px; color:#333;')
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setAlignment(Qt.AlignCenter)
        root.addWidget(self._lbl_status)

        # ── Botão Run ─────────────────────────────────────────────────────────
        self._btn_run = QPushButton('▶  Executar / Run')
        self._btn_run.setMinimumHeight(40)
        self._btn_run.setStyleSheet(
            'QPushButton{background:#1a73e8;color:white;border-radius:4px;'
            'font-size:13px;font-weight:bold;}'
            'QPushButton:hover{background:#1558b0;}'
            'QPushButton:disabled{background:#aaa;color:#eee;}')
        self._btn_run.clicked.connect(self._on_run)
        self._btn_run.setEnabled(False)   # habilitado assim que o caminho de saída for preenchido
        root.addWidget(self._btn_run)

        self._btn_cancel = QPushButton('✖  Cancelar / Cancel')
        self._btn_cancel.setMinimumHeight(34)
        self._btn_cancel.setStyleSheet(
            'QPushButton{background:#d93025;color:white;border-radius:4px;'
            'font-size:12px;font-weight:bold;}'
            'QPushButton:hover{background:#a50e0e;}'
            'QPushButton:disabled{background:#e8a8a4;color:#fff;}')
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_cancel.setVisible(False)
        root.addWidget(self._btn_cancel)

    # ── Preenchimento de camadas ───────────────────────────────────────────────

    def _populate_layers(self):
        # QUANDO É CHAMADO: no __init__ e novamente em RthMLTool.run() cada vez
        # que o usuário reabre o diálogo — garante que novas camadas carregadas
        # após a primeira abertura apareçam nas combo boxes.
        #
        # QgsProject.instance() → singleton do projeto QGIS ativo.
        # mapLayers() → dicionário {layer_id: QgsMapLayer} de TODAS as camadas.
        # Usamos o id() como userData da combo (não o objeto layer) para evitar
        # referências soltas — o objeto pode ser deletado enquanto o diálogo está aberto.
        project = QgsProject.instance()
        self._combo_raster.clear()
        self._combo_vector.clear()

        for layer in project.mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid():
                self._combo_raster.addItem(layer.name(), layer.id())
            elif isinstance(layer, QgsVectorLayer) and layer.isValid():
                self._combo_vector.addItem(layer.name(), layer.id())

        self._on_vector_changed(0)   # preenche o combo de campos para a camada padrão

    def _on_vector_changed(self, _idx):
        # QUANDO É CHAMADO: sinal currentIndexChanged da combo de amostras.
        # Sempre que o usuário troca a camada vetorial, recarregamos os campos —
        # cada camada tem um schema diferente e o campo de classes muda.
        # _idx é o índice da nova seleção, mas não precisamos dele aqui.
        self._combo_field.clear()
        lid = self._combo_vector.currentData()
        if not lid:
            return
        layer = QgsProject.instance().mapLayer(lid)
        if layer:
            for field in layer.fields():
                self._combo_field.addItem(field.name(), field.name())

    # ── Handlers UI ───────────────────────────────────────────────────────────

    def _on_out_path_changed(self, text):
        self._btn_run.setEnabled(bool(text.strip()))

    def _on_model_changed(self, _idx):
        # QUANDO É CHAMADO: sinal currentIndexChanged da combo de modelo.
        # Mostra/esconde o grupo de parâmetros correspondente ao modelo selecionado.
        # setVisible(False) oculta o widget sem destruí-lo — os valores são preservados
        # se o usuário trocar de modelo e voltar.
        key = self._combo_model.currentData()
        self._group_rf.setVisible(key == 'RF')
        self._group_et.setVisible(key == 'ET')
        self._group_gb.setVisible(key == 'GB')
        self._group_svm.setVisible(key == 'SVM')
        self._group_knn.setVisible(key == 'KNN')
        self._group_nb.setVisible(key == 'NB')
        self._group_gmm.setVisible(key == 'GMM')
        self._group_gmm_sk.setVisible(key == 'GMM_SK')

    def _on_split_toggled(self, state):
        # QUANDO É CHAMADO: sinal stateChanged do checkbox de split amostral.
        # state == 2 significa Qt.Checked (marcado). Não é bool — Qt usa int:
        #   0 = Qt.Unchecked, 1 = Qt.PartiallyChecked, 2 = Qt.Checked.
        # Habilitamos o spinbox e o checkbox de matriz só quando o split está ativo,
        # pois a matriz de confusão requer amostras de teste (separadas pelo split).
        active = state == 2
        self._spin_split.setEnabled(active)
        self._chk_matrix.setEnabled(active)
        if not active:
            self._chk_matrix.setChecked(False)

    def _on_browse_out(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Salvar raster classificado / Save classified raster',
            '', 'GeoTIFF (*.tif)')
        if path:
            if not path.lower().endswith('.tif'):
                path += '.tif'
            self._edit_out.setText(path)

    def _on_run(self):
        # QUANDO É CHAMADO: clique no botão "Executar / Run".
        # Fluxo:
        #   1. Verifica dependências (sklearn) — antes dos campos para dar feedback imediato
        #   2. Valida campos obrigatórios
        #   3. Resolve caminhos em disco (pode exportar camada de memória)
        #   4. Cria e inicia o _MLWorker com todos os parâmetros
        #   5. Conecta os sinais do worker aos slots da UI
        dep = _check_deps(self._combo_model.currentData())
        if dep is not None:
            kind, msg = dep
            if kind == 'no_sklearn':
                self._ask_install_sklearn()
                return
            QMessageBox.warning(
                self, 'RTH Machine Learning — Dependência Faltando / Missing Dependency', msg)
            return

        if not self._validate():
            return

        # Desabilita o botão para evitar duplo-clique enquanto o worker está rodando.
        # Reabilitado em _on_finished() ou _on_error().
        self._btn_run.setEnabled(False)
        self._progress.setValue(0)
        self._set_status_normal('')   # limpa estilo de erro/ok de uma execução anterior

        # Verifica CRS antes de iniciar: se o raster e o vetor estão em sistemas de
        # coordenadas diferentes, a rasterização vai queimar os polígonos fora da imagem,
        # e a extração de amostras retornará apenas 1 classe ou nenhuma.
        # Semelhante à verificação de CRS que o dzetsaka faz no runMagic().
        self._check_crs_match()

        raster_path = self._resolve_raster_path()
        vector_path = self._resolve_vector_path()
        if raster_path is None or vector_path is None:
            self._btn_run.setEnabled(bool(self._edit_out.text().strip()))
            return

        model_key = self._combo_model.currentData()
        if model_key == 'RF':
            model_params = {
                'n_estimators': self._spin_n_est.value(),
                'max_depth':    self._spin_max_depth.value() or None,
            }
        elif model_key == 'ET':
            model_params = {
                'n_estimators': self._spin_et_n_est.value(),
                'max_depth':    self._spin_et_depth.value() or None,
            }
        elif model_key == 'GB':
            model_params = {
                'max_iter':      self._spin_gb_iter.value(),
                'learning_rate': self._spin_gb_lr.value(),
            }
        elif model_key == 'SVM':
            model_params = {'C': self._spin_svm_c.value()}
        elif model_key == 'KNN':
            model_params = {'n_neighbors': self._spin_knn_k.value()}
        elif model_key == 'GMM_SK':
            model_params = {'reg_param': self._spin_qda_reg.value()}
        else:   # GMM nativo, NB — sem parâmetros externos
            model_params = {}

        split_pct   = self._spin_split.value() if self._chk_split.isChecked() else None
        save_matrix = self._chk_matrix.isChecked()

        # Guardamos o worker em self._worker para que o garbage collector do Python
        # não destrua o objeto enquanto a thread está rodando (o Qt não segura referência).
        self._worker = _MLWorker(
            raster_path=raster_path,
            vector_path=vector_path,
            field=self._combo_field.currentData(),
            model_key=model_key,
            model_params=model_params,
            out_path=self._edit_out.text().strip(),
            split_pct=split_pct,
            save_matrix=save_matrix,
        )
        # Conexão sinal → slot: cada .connect() registra um callback thread-safe.
        # O Qt garante que os slots são chamados na thread principal, mesmo que
        # os sinais sejam emitidos pela thread do worker.
        self._worker.progress.connect(self._progress.setValue)
        self._worker.status.connect(self._set_status_normal)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        # diag → messageBar: emitido uma vez após extração das amostras.
        # Mostra a distribuição de classes (Cls1: 300px, Cls2: 250px…) de forma
        # persistente na barra do QGIS, mesmo quando o label de status já mudou.
        self._worker.diag.connect(self._on_diag)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()   # inicia a thread (chama run() em background)
        self._btn_cancel.setVisible(True)
        self._btn_cancel.setEnabled(True)
        self._btn_cancel.setText('✖  Cancelar / Cancel')

    # ── Helpers de estilo do label de status ──────────────────────────────────

    def _set_status_normal(self, text):
        self._lbl_status.setStyleSheet('font-size:13px; color:#333;')
        self._lbl_status.setText(text)

    def _set_status_ok(self, text):
        self._lbl_status.setStyleSheet(
            'font-size:13px; color:#1a7a3c; background:#e8f5e9;'
            'border:1px solid #a5d6a7; border-radius:4px; padding:6px 8px;')
        self._lbl_status.setText(text)

    def _set_status_error(self, text):
        self._lbl_status.setStyleSheet(
            'font-size:12px; color:#b71c1c; background:#fdf0ef;'
            'border:1px solid #e8a8a4; border-radius:4px; padding:6px 8px;')
        self._lbl_status.setText(text)

    def _set_status_warning(self, text):
        self._lbl_status.setStyleSheet(
            'font-size:13px; color:#7a5500; background:#fff8e1;'
            'border:1px solid #ffe082; border-radius:4px; padding:6px 8px;')
        self._lbl_status.setText(text)

    # ── Handlers do worker ────────────────────────────────────────────────────

    def _on_finished(self, out_path):
        # QUANDO É CHAMADO: sinal finished do worker — classificação concluída com sucesso.
        # Aqui carregamos o raster classificado no projeto QGIS e aplicamos contraste.
        self._btn_run.setEnabled(bool(self._edit_out.text().strip()))
        self._btn_cancel.setVisible(False)
        # QgsRasterLayer(caminho, nome) — cria um objeto de camada em memória.
        # A camada só fica visível no QGIS após addMapLayer().
        layer = QgsRasterLayer(out_path, os.path.splitext(os.path.basename(out_path))[0])
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            # O raster classificado tem tipo UInt16 com valores 1, 2, 3…
            # O QGIS renderiza UInt16 com escala 0–65535 por padrão, tornando
            # valores pequenos (1, 2, 3) quase invisíveis (quase preto).
            # setContrastEnhancement() com StretchToMinimumMaximum recalcula
            # a escala de cor para [min_real, max_real] — os labels ficam visíveis.
            # O try/except existe porque a assinatura mudou entre QGIS 3 e 4;
            # as constantes _CE_STRETCH/_CE_LIMITS já resolvem isso no topo,
            # mas o try aqui protege contra qualquer edge case inesperado.
            try:
                layer.setContrastEnhancement(_CE_STRETCH, _CE_LIMITS)
                layer.triggerRepaint()
            except Exception:
                pass
        self._set_status_ok(
            '✔  Concluído: {} / Complete: {}'.format(
                os.path.basename(out_path), os.path.basename(out_path)))

    def _on_cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._btn_cancel.setEnabled(False)
            self._btn_cancel.setText('Cancelando... / Cancelling...')
            self._set_status_warning('Aguardando o bloco atual terminar... / Finishing current block...')

    def _on_cancelled(self):
        self._btn_run.setEnabled(bool(self._edit_out.text().strip()))
        self._btn_cancel.setVisible(False)
        self._btn_cancel.setText('✖  Cancelar / Cancel')
        self._progress.setValue(0)
        self._set_status_warning('Cancelado pelo usuário / Cancelled by user')

    def _on_error(self, msg):
        self._btn_run.setEnabled(bool(self._edit_out.text().strip()))
        self._btn_cancel.setVisible(False)
        self._set_status_error('⚠  ' + msg)

    # ── Instalação automática de scikit-learn ─────────────────────────────────

    def _ask_install_sklearn(self):
        """Mostra diálogo perguntando se quer instalar scikit-learn agora /
        Shows dialog asking whether to install scikit-learn now."""
        # Criamos o QMessageBox manualmente (não via QMessageBox.warning()) porque
        # precisamos de um botão customizado ("Instalar Agora") que não existe nos
        # métodos estáticos. AcceptRole e RejectRole definem o comportamento ao
        # pressionar Enter ou Escape, mas não afetam o texto do botão.
        box = QMessageBox(self)
        box.setWindowTitle('RTH Machine Learning — scikit-learn')
        box.setIcon(_MB_ICON_WARNING)   # constante de compat definida no topo do arquivo
        box.setText(
            'scikit-learn não está instalado.\n'
            'É necessário para usar este modelo (RF, SVM, KNN, Extra Trees, etc.).\n\n'
            'Deseja instalar automaticamente agora?\n'
            '(requer conexão com a internet — pode levar alguns minutos)\n\n'
            '─────────────────────────────────────\n'
            'scikit-learn is not installed.\n'
            'Required for this model (RF, SVM, KNN, Extra Trees, etc.).\n\n'
            'Install automatically now?\n'
            '(requires internet — may take a few minutes)')
        btn_install = box.addButton(
            'Instalar Agora / Install Now', _MB_ACCEPT_ROLE)
        box.addButton('Cancelar / Cancel', _MB_REJECT_ROLE)
        box.exec_()
        # clickedButton() retorna o objeto QAbstractButton que foi clicado.
        # Comparamos por identidade (is) para saber qual botão específico foi acionado.
        if box.clickedButton() is btn_install:
            self._run_pip_install()

    def _run_pip_install(self):
        self._btn_run.setEnabled(False)
        self._progress.setValue(0)
        self._set_status_warning(
            '⏳  Instalando o pacote, aguarde... / Installing package, please wait...')
        self._install_worker = _PipInstallWorker('scikit-learn')
        # status → atualiza o label em tempo real com cada linha do pip (Downloading, Installing…)
        self._install_worker.status.connect(self._set_status_warning)
        self._install_worker.finished.connect(self._on_pip_finished)
        self._install_worker.start()

    def _on_pip_finished(self, success, err_msg):
        self._btn_run.setEnabled(bool(self._edit_out.text().strip()))
        if success:
            self._set_status_ok(
                '✔  scikit-learn instalado com sucesso! Clique em Executar para classificar. / '
                'scikit-learn installed successfully! Click Run to classify.')
            self._progress.setValue(100)
        else:
            self._set_status_error(
                '⚠  Falha na instalação. Tente manualmente via OSGeo4W Shell:\n'
                'pip install scikit-learn\n\n'
                'Install failed. Try manually via OSGeo4W Shell:\n'
                'pip install scikit-learn\n\n'
                + err_msg[:300])

    # ── Validação e resolução de caminhos ──────────────────────────────────────

    def _check_crs_match(self):
        """Compara o CRS do raster e do vetor; avisa se forem diferentes /
        Compare raster and vector CRS; warn if they differ.

        Não bloqueia a execução — é apenas um aviso. O GDAL/OGR não reprojecta
        automaticamente durante a rasterização: polígonos em CRS diferente caem
        fora do extent do raster, resultando em amostras vazias ou apenas 1 classe.
        Does not block execution — warning only. GDAL does not auto-reproject during
        rasterization: polygons in wrong CRS fall outside raster extent.
        """
        try:
            r_lid = self._combo_raster.currentData()
            v_lid = self._combo_vector.currentData()
            r_layer = QgsProject.instance().mapLayer(r_lid)
            v_layer = QgsProject.instance().mapLayer(v_lid)
            if r_layer is None or v_layer is None:
                return
            r_crs = r_layer.crs()
            v_crs = v_layer.crs()
            if not r_crs.isValid() or not v_crs.isValid():
                return
            if r_crs.authid() != v_crs.authid():
                self.iface.messageBar().pushMessage(
                    'RTH ML — CRS',
                    'Raster ({}) e amostras ({}) em CRS diferentes — '
                    'reprojeção automática será aplicada durante a rasterização. / '
                    'Raster ({}) and samples ({}) in different CRS — '
                    'automatic reprojection will be applied during rasterization.'.format(
                        r_crs.authid(), v_crs.authid(),
                        r_crs.authid(), v_crs.authid()),
                    level=Qgis.MessageLevel.Info, duration=8)
        except Exception:
            pass   # verificação opcional — não bloqueia se falhar / optional check

    def _on_diag(self, msg):
        """Empurra a mensagem de diagnóstico de amostras para a messageBar do QGIS /
        Push sample diagnostic message to QGIS message bar.

        O label de status (_lbl_status) é sobrescrito a cada status.emit(), então
        a distribuição de classes (crucial para debug) seria perdida. Enviando para
        a messageBar (que persiste até o usuário fechar), garantimos que o usuário
        sempre pode ver quantas amostras por classe foram extraídas.
        """
        self.iface.messageBar().pushMessage(
            'RTH ML — Amostras / Samples',
            msg,
            level=Qgis.MessageLevel.Info, duration=0)

    def _validate(self):
        # QUANDO É CHAMADO: início de _on_run(), após a verificação de dependências.
        # Retorna False e mostra mensagem no label de status se algum campo estiver vazio.
        # Preferimos feedback inline (no label) a QMessageBox aqui porque é mais rápido
        # para o usuário — sem clique extra em "OK".
        if not self._combo_raster.currentData():
            self._set_status_warning('Selecione uma imagem raster. / Select a raster image.')
            return False
        if not self._combo_vector.currentData():
            self._set_status_warning('Selecione uma camada de amostras. / Select a sample layer.')
            return False
        if not self._combo_field.currentData():
            self._set_status_warning('Selecione o campo de classes. / Select the class field.')
            return False
        if not self._edit_out.text().strip():
            self._set_status_warning('Defina o arquivo de saída. / Set the output file.')
            return False
        return True

    def _resolve_raster_path(self):
        # QGIS armazena o source de camadas com metadados extras após '|'.
        # Ex: "/path/to/file.gpkg|layername=minha_camada"
        # Precisamos só do caminho de arquivo → split no '|'.
        lid = self._combo_raster.currentData()
        layer = QgsProject.instance().mapLayer(lid)
        if layer is None:
            return None
        path = layer.source()
        if '|' in path:
            path = path.split('|')[0]
        return path

    def _resolve_vector_path(self):
        """Retorna caminho em disco da camada vetorial, exportando para temp se necessário /
        Returns disk path of the vector layer, exporting to temp if needed.

        Camadas de memória (criadas com 'memory' no URI, como as geradas por scripts)
        não têm arquivo em disco. GDAL/OGR não consegue abri-las diretamente.
        Nesse caso, exportamos para um GeoPackage temporário antes de passar para o worker.
        """
        lid = self._combo_vector.currentData()
        layer = QgsProject.instance().mapLayer(lid)
        if layer is None:
            return None

        src = layer.source()
        if '|' in src:
            src = src.split('|')[0]

        # Camada em disco — usar diretamente (GDAL consegue abrir esses formatos)
        for ext in ('.shp', '.gpkg', '.geojson', '.json', '.sqlite', '.kml', '.gml'):
            if src.lower().endswith(ext) and os.path.isfile(src):
                return src

        # Camada de memória ou virtual → exportar para GeoPackage temporário.
        # QgsVectorFileWriter.writeAsVectorFormatV2() é a API QGIS 3.x para exportar.
        # O try/except existe porque algumas versões do QGIS retornam 4 valores
        # (err, msg, newFilename, newLayer) e outras retornam só 2 (err, msg).
        self._lbl_status.setText(
            'Exportando camada de memória para arquivo temporário... / '
            'Exporting memory layer to temporary file...')
        tmp = tempfile.mktemp(suffix='.gpkg')
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = 'GPKG'
        opts.fileEncoding = 'UTF-8'
        try:
            err, msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer, tmp, QgsCoordinateTransformContext(), opts)
        except TypeError:
            err, msg = QgsVectorFileWriter.writeAsVectorFormatV2(
                layer, tmp, QgsCoordinateTransformContext(), opts)

        if err != QgsVectorFileWriter.NoError:
            self._on_error(
                'Não foi possível exportar a camada de amostras: {} / '
                'Could not export sample layer: {}'.format(msg, msg))
            return None
        return tmp


# ── Ferramenta principal ──────────────────────────────────────────────────────

class RthMLTool:
    # Esta é a classe "entry point" que o plugin RTH PROJECT.py conhece.
    # Ela NÃO herda de QDialog nem de QgsMapTool — é um wrapper simples
    # que gerencia o ciclo de vida do diálogo.
    #
    # Padrão singleton de diálogo: criamos RthMLDialog uma vez e reutilizamos.
    # Isso preserva o estado dos campos entre chamadas (o usuário não precisa
    # reconfigurar tudo se fechar e reabrir acidentalmente).
    """Ferramenta RTH Machine Learning / RTH Machine Learning tool."""

    def __init__(self, iface):
        self.iface   = iface
        self._dialog = None   # None até a primeira vez que run() é chamado

    def run(self):
        # QUANDO É CHAMADO: ação de menu no RTH PROJECT.py → self.tool_rth_ml.run()
        #
        # A verificação `not self._dialog.isVisible()` garante que se o diálogo
        # foi fechado pelo usuário (não só minimizado), ele seja recriado limpo.
        # Se já estiver visível, apenas traz para frente (raise_ + activateWindow).
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = RthMLDialog(self.iface, self.iface.mainWindow())
        self._dialog.show()
        self._dialog.raise_()          # traz para frente de outras janelas
        self._dialog.activateWindow()  # dá foco ao teclado
        # Recarrega as camadas do projeto para capturar novas camadas abertas
        # desde a última vez que o diálogo foi exibido.
        self._dialog._populate_layers()
