# Pasta Mock — Bases Geográficas Locais
## Mock Folder — Local Geographic Data

---

## Português

Esta pasta é utilizada pelo plugin **RTH** para exibir bases vetoriais personalizadas diretamente no menu **Bases Geográficas**, de forma dinâmica. Qualquer arquivo colocado aqui aparecerá automaticamente como um item no menu ao abri-lo — sem necessidade de reiniciar o QGIS.

### Como usar

1. Copie qualquer arquivo vetorial para esta pasta.
2. Abra o menu **Bases Geográficas** na barra de ferramentas do plugin.
3. O arquivo aparecerá listado automaticamente. Clique para carregá-lo no projeto.

### Formatos suportados

`.gpkg` · `.shp` · `.geojson` · `.json` · `.kml` · `.kmz`

### Nome exibido no menu

O nome exibido é gerado automaticamente a partir do nome do arquivo, substituindo `_` e `-` por espaços. Exemplo: `grade_brasil_25km.gpkg` → `grade brasil 25km`.

### Onde encontrar grades e tiling grids

Grades do Brasil (10 km, 25 km) e tiling grids do Sentinel-2 e Landsat 8 para uso com este plugin estão disponíveis no repositório:

**[https://github.com/RithonBR/Projeto_Padrao_Qgis/tree/master/dados%20abertos/Grades](https://github.com/RithonBR/Projeto_Padrao_Qgis/tree/master/dados%20abertos/Grades)**

Faça o download dos arquivos desejados e coloque-os nesta pasta.

---

## English

This folder is used by the **RTH** plugin to display custom vector datasets directly in the **Geographic Data** menu, dynamically. Any file placed here will automatically appear as a menu item when the menu is opened — no QGIS restart required.

### How to use

1. Copy any vector file into this folder.
2. Open the **Geographic Data** menu in the plugin toolbar.
3. The file will be listed automatically. Click it to load it into the project.

### Supported formats

`.gpkg` · `.shp` · `.geojson` · `.json` · `.kml` · `.kmz`

### Display name in menu

The displayed name is automatically generated from the file name, replacing `_` and `-` with spaces. Example: `grade_brasil_25km.gpkg` → `grade brasil 25km`.

### Where to find grids and tiling grids

Brazil grids (10 km, 25 km) and Sentinel-2 / Landsat 8 tiling grids for use with this plugin are available in the repository:

**[https://github.com/RithonBR/Projeto_Padrao_Qgis/tree/master/dados%20abertos/Grades](https://github.com/RithonBR/Projeto_Padrao_Qgis/tree/master/dados%20abertos/Grades)**

Download the desired files and place them in this folder.
