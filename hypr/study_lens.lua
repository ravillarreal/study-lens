-- Study Lens: atajos y regla de ventana para Hyprland (Omarchy).
-- Este archivo lo instala y actualiza `study-lens --setup`; no lo edites a mano.
-- Los atajos se cambian desde el panel (botón ⌨ Atajos), que los guarda en
-- ~/.config/study-lens/shortcuts.lua.

local keys = {
  region  = { "SUPER + ALT + X" },
  more    = { "SUPER + ALT + C" },
  analyze = { "SUPER + ALT + V" },
  new     = { "SUPER + ALT + Z" },
  window  = { "SUPER + ALT + A" },
  toggle  = { "SUPER + ALT + Q" },
}
do
  local chunk = loadfile(os.getenv("HOME") .. "/.config/study-lens/shortcuts.lua")
  local ok, user = pcall(chunk or function() end)
  if ok and type(user) == "table" then
    for action, combos in pairs(user) do keys[action] = combos end
  end
end

local names = {
  region = "analizar región", more = "otra captura (tras scroll)", analyze = "analizar capturas",
  new = "nuevo ejercicio", window = "analizar ventana", toggle = "mostrar/ocultar panel",
}
-- El "(--acción)" de la descripción le dice a la app qué atajo es cuál.
for action, combos in pairs(keys) do
  for _, combo in ipairs(combos) do
    o.bind(combo, "Study Lens: " .. (names[action] or action) .. " (--" .. action .. ")",
      "study-lens --" .. action)
  end
end

-- Panel flotante a la derecha.
o.window("^dev\\.zavu\\.StudyLens$", {
  tag = "-default-opacity",
  opacity = "1 1",
  no_initial_focus = true,
  float = true,
  size = { "(monitor_w*0.32)", "(monitor_h*0.85)" },
  move = { "(monitor_w*0.67)", "(monitor_h*0.08)" },
})
