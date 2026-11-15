# Changelog

## [0.1.0](https://github.com/ravillarreal/study-lens/releases/tag/v0.1.0) (2026-11-15)

Primera versión pública.

### Novedades

* Captura una región o la ventana activa y la manda a un modelo vía opencode (OpenCode Go por API directa con streaming, o cualquier proveedor con `opencode run`).
* Varias capturas por ejercicio (para enunciados que necesitan scroll), con ✕ para quitar las que todavía no se mandaron, y preguntas de seguimiento.
* Fórmulas LaTeX dibujadas en el panel con ziamath, con respaldo en Unicode.
* Ventana de atajos: asigna cualquier combinación de teclas o botón del mouse desde el programa.
* `study-lens --setup` / `--unsetup` instalan y quitan los atajos y la regla de ventana en Hyprland.
* Ejecutable de un solo archivo: `./study-lens --setup` instala el comando, el lanzador y los atajos, sin sudo.
