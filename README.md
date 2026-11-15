# Study Lens

Panel para Hyprland que captura un ejercicio en tu pantalla (una región o la ventana activa), se lo manda a un modelo de IA vía [opencode](https://opencode.ai) y te muestra la explicación paso a paso, con las fórmulas bien dibujadas.

Pensado para estudiar: tomas una o varias capturas del enunciado (haciendo scroll si no cabe), pides el análisis y después puedes hacer preguntas de seguimiento.

## Instalación

En **Omarchy** no hace falta instalar nada más que opencode:

1. Instala [opencode](https://opencode.ai) e inicia sesión con `opencode auth login`.
   - Con el plan **OpenCode Go**, los modelos `opencode-go/…` van por API directa, con streaming. Es la opción rápida.
   - Cualquier otro modelo o proveedor que tengas en opencode funciona a través de `opencode run`, que es más lento.
2. Baja el ejecutable `study-lens` del [último release](https://github.com/ravillarreal/study-lens/releases/latest) y córrelo una vez con `--setup`:
   ```bash
   curl -fLO https://github.com/ravillarreal/study-lens/releases/latest/download/study-lens
   chmod +x study-lens && ./study-lens --setup
   ```
   Eso deja el comando en `~/.local/bin`, agrega Study Lens al lanzador de aplicaciones e instala los atajos y la regla de ventana en Hyprland. Antes guarda una copia de `bindings.lua`. Después puedes borrar el archivo que bajaste.

**Actualizar:** baja el ejecutable nuevo y vuelve a correr `./study-lens --setup`.

**Desinstalar:** `study-lens --unsetup`. Tus atajos y la configuración quedan en `~/.config/study-lens`.

El ejecutable es un solo archivo de ~1,5 MB que trae el programa y sus dependencias de Python. Usa el `python3` y GTK4 del sistema, que Omarchy ya trae. En otro Arch con Hyprland necesitas además:

```bash
sudo pacman -S --needed python-gobject gtk4 grim slurp
```

Los atajos se instalan en la configuración Lua de Hyprland que usa Omarchy (`~/.config/hypr/bindings.lua`). En otras configuraciones el panel funciona, pero tendrás que poner los atajos a mano.

### Desde el código

```bash
git clone https://github.com/ravillarreal/study-lens.git && cd study-lens && ./install.sh
```

## Uso

| Atajo por defecto | Acción |
|---|---|
| `Super+Alt+X` | Analizar una región (la eliges con el mouse) |
| `Super+Alt+C` | Otra captura del mismo lugar (después de hacer scroll) |
| `Super+Alt+V` | Mandar las capturas al modelo |
| `Super+Alt+Z` | Nuevo ejercicio (vuelve a capturar la misma región) |
| `Super+Alt+A` | Analizar la ventana activa |
| `Super+Alt+Q` | Mostrar u ocultar el panel |

Para cambiarlos, abre el botón **⌨ Atajos** del panel. Pulsa **+ Agregar** y presiona la combinación o el botón del mouse que quieras usar. Los cambios se aplican al instante.

En el panel también puedes:
- Elegir el modelo.
- Ver las capturas del ejercicio (clic: ampliar; ✕: quitar una que todavía no mandaste).
- Escribir preguntas de seguimiento.
- Moverte por la respuesta con el teclado: `j`/`k`, `espacio`, `g`/`G`.

### Línea de comandos

```
study-lens              abre o enfoca el panel
study-lens --region     selecciona una región y la captura
study-lens --window     captura la ventana activa
study-lens --more       otra captura del mismo objetivo
study-lens --analyze    manda las capturas pendientes al modelo
study-lens --new        nuevo ejercicio
study-lens --toggle     muestra u oculta el panel
study-lens --shortcuts  ventana de atajos
study-lens --setup      instala atajos y regla de ventana en Hyprland
study-lens --unsetup    los quita
study-lens --version
```

## Archivos

| Ruta | Qué guarda |
|---|---|
| `~/.config/study-lens/config.json` | El modelo elegido |
| `~/.config/study-lens/shortcuts.lua` | Tus atajos |
| `~/.config/hypr/study_lens.lua` | Atajos y regla de ventana para Hyprland. Lo genera `--setup`; no lo edites a mano |
| `~/.cache/study-lens/` | Capturas y registro (`study-lens.log`) |

Las instrucciones que sigue el tutor están en `.opencode/agent/tutor.md`.

## Desarrollo

Los commits siguen [Conventional Commits](https://www.conventionalcommits.org/es/):
- `feat: …` para algo nuevo.
- `fix: …` para una corrección.
- `feat!: …` cuando algo rompe compatibilidad.

[release-please](https://github.com/googleapis/release-please) arma con ellos un PR de release que actualiza `CHANGELOG.md` y la versión. Al hacer merge de ese PR se publica el release y GitHub Actions le adjunta el ejecutable.

Para armar el ejecutable a mano: `pip install shiv && scripts/build.sh` (queda en `dist/study-lens`).

## Licencia

[MIT](LICENSE)
