# greenroom

**Cientos de skills de Claude Code fuera del contexto, sin perder ninguna.**

[English](README.md)

En un teatro, el *green room* es la sala donde los artistas esperan fuera de escena: no ocupan el escenario, pero están listos, y el regidor sabe quién está ahí y los llama cuando toca su número. greenroom hace eso con las skills de Claude Code.

## El problema

Cada skill instalada mete su nombre y su descripción en el contexto de **todas** las sesiones. Pasadas unas decenas, eso pesa. Cuando el listado supera ~1% del contexto, Claude Code empieza a recortar descripciones, y el modelo elige peor o nunca encuentra la skill justa.

Los arreglos de siempre lo empeoran:
- **Desinstalar** pierde la skill.
- **`skillOverrides: "off"`** ahorra contexto, pero además saca `/nombre` de **tu** menú. Encima, nada le avisa al modelo que la skill existe, así que improvisa.

## Cómo lo resuelve

1. **Familias y puertas.** Las skills se agrupan en familias, y cada una tiene una **puerta**: una sola skill visible que elige las que hacen falta y lee su `SKILL.md` desde disco.
2. **Ocultas, nunca apagadas.** Las miembros quedan en `"user-invocable-only"`: no ocupan contexto y siguen en tu menú `/`. greenroom nunca escribe `"off"` y convierte el que encuentre.
3. **Mapa al iniciar sesión.** Un hook `SessionStart` inyecta un mapa corto con qué hay oculto, qué puertas existen y cuáles necesita **este repo**. Detecta el stack por `package.json`, por archivos de config y por librerías cargadas por CDN en sitios HTML de un solo archivo.
4. **Mantenimiento cero.** Al iniciar cada sesión, y justo después de cada `skills add/remove` o `plugin install/uninstall`, greenroom:
   - clasifica las skills nuevas;
   - las oculta;
   - las suma a su puerta;
   - poda las borradas.

   Si una skill no tiene una familia clara, queda visible y el mapa la marca.
5. **Cero huérfanas.** `check` falla si alguna skill oculta no tiene puerta, si una puerta está oculta o si queda algo en `"off"`.

## Instalar

```bash
git clone https://github.com/PapiScholz/greenroom
cd greenroom
python install.py --dry-run     # vista previa: a qué familia iría cada skill
python install.py               # instala (pregunta antes de ocultar)
```

Para desinstalar:

```bash
python install.py --uninstall
```

Restaura cada override que greenroom cambió, quita los hooks y borra las puertas generadas. No toca tus skills.

El resto (registro, comandos, límites) está en el [README en inglés](README.md).
