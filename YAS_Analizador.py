
import os
import re
from collections import Counter
from flask import Flask, request, jsonify, render_template
import webbrowser
import threading

app = Flask(__name__)

# ============================================================
# 1. REGLAS DE RECONOCIMIENTO DE CADA LENGUAJE
# ============================================================

REGLAS = {
    "Python": {
        "reservadas": set("""
            False None True and as assert async await break class
            continue def del elif else except finally for from
            global if import in is lambda nonlocal not or pass
            raise return try while with yield
        """.split()),
        "operadores": [
            "**=", "//=", ">>=", "<<=", ":=", "==", "!=", "<=", ">=",
            "+=", "-=", "*=", "/=", "%=", "**", "//", "<<", ">>",
            "=", "+", "-", "*", "/", "%", "<", ">", "&", "|", "^",
            "~", "->"
        ],
        "delimitadores": set("()[]{}"),
        "puntuacion": set(".,:;@")
    },

    "JavaScript": {
        "reservadas": set("""
            break case catch class const continue debugger default
            delete do else export extends finally for function if
            import in instanceof let new return super switch this
            throw try typeof var void while with yield async await
            of true false null undefined
        """.split()),
        "operadores": [
            "===", "!==", "=>", "++", "--", "**", "==", "!=", "<=",
            ">=", "&&", "||", "??", "?.", "+=", "-=", "*=", "/=",
            "=", "+", "-", "*", "/", "%", "<", ">", "!", "&",
            "|", "^", "~"
        ],
        "delimitadores": set("()[]{}"),
        "puntuacion": set(".,:;")
    },

    "C++": {
        "reservadas": set("""
            alignas alignof and asm auto bool break case catch char
            class const constexpr continue decltype default delete do
            double else enum explicit extern false float for friend
            goto if inline int long namespace new noexcept not nullptr
            operator private protected public register return short
            signed sizeof static struct switch template this throw true
            try typedef typename union unsigned using virtual void
            volatile while std string include define
        """.split()),
        "operadores": [
            "<<=", ">>=", "++", "--", "->", "::", "==", "!=", "<=",
            ">=", "&&", "||", "<<", ">>", "+=", "-=", "*=", "/=",
            "=", "+", "-", "*", "/", "%", "<", ">", "!", "&",
            "|", "^", "~"
        ],
        "delimitadores": set("()[]{}"),
        "puntuacion": set(".,:;#")
    }
}


# ============================================================
# 2. ANALIZADOR LÉXICO
# ============================================================

def analizar_codigo(codigo, lenguaje):

    reglas = REGLAS[lenguaje]

    tokens = []
    errores = []

    i = 0
    linea = 1
    columna = 1
    n = len(codigo)

    def agregar(lexema, categoria, inicio, fin,
                lin, col, valido=True, mensaje=""):

        token = {
            "lexema": lexema,
            "categoria": categoria,
            "linea": lin,
            "columna": col,
            "valido": valido,
            "estado": "Válido" if valido else "Error",
            "descripcion_error": mensaje,
            "start_idx": inicio,
            "end_idx": fin
        }

        tokens.append(token)

        if not valido:
            errores.append(token.copy())

    while i < n:

        inicio = i
        lin = linea
        col = columna
        ch = codigo[i]

        # Espacios y saltos de línea
        if ch.isspace():

            if ch == "\n":
                linea += 1
                columna = 1
            else:
                columna += 1

            i += 1
            continue

        # Comentarios de una línea
        if codigo.startswith("#", i) or (
            lenguaje != "Python" and codigo.startswith("//", i)
        ):

            fin = codigo.find("\n", i)

            if fin == -1:
                fin = n

            agregar(
                codigo[i:fin], "Comentario",
                i, fin, lin, col
            )

            columna += fin - i
            i = fin
            continue

        # Comentarios de bloque
        if lenguaje != "Python" and codigo.startswith("/*", i):

            cierre = codigo.find("*/", i + 2)

            if cierre == -1:

                agregar(
                    codigo[i:], "Error léxico",
                    i, n, lin, col, False,
                    "Comentario de bloque sin cerrar."
                )

                columna += n - i
                i = n

            else:

                fin = cierre + 2
                lexema = codigo[i:fin]

                agregar(
                    lexema, "Comentario",
                    i, fin, lin, col
                )

                saltos = lexema.count("\n")

                if saltos:
                    linea += saltos
                    columna = len(lexema.rsplit("\n", 1)[-1]) + 1
                else:
                    columna += len(lexema)

                i = fin

            continue

        # Cadenas de texto
        if ch in ("'", '"', "`"):

            comilla = ch
            j = i + 1
            escapado = False
            cerrada = False

            while j < n:

                actual = codigo[j]

                if (
                    actual == "\n"
                    and comilla != "`"
                    and not escapado
                ):
                    break

                if actual == comilla and not escapado:
                    j += 1
                    cerrada = True
                    break

                if actual == "\\" and not escapado:
                    escapado = True
                else:
                    escapado = False

                j += 1

            lexema = codigo[i:j]

            if cerrada:

                agregar(
                    lexema, "Cadena",
                    i, j, lin, col
                )

            else:

                agregar(
                    lexema, "Error léxico",
                    i, j, lin, col, False,
                    "Cadena de texto sin cerrar."
                )

            columna += j - i
            i = j
            continue

        # Números
        coincidencia = re.match(
            r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?",
            codigo[i:]
        )

        if coincidencia:

            lexema = coincidencia.group(0)
            j = i + len(lexema)

            if j < n and (
                codigo[j].isalpha() or codigo[j] == "_"
            ):

                while j < n and (
                    codigo[j].isalnum() or codigo[j] == "_"
                ):
                    j += 1

                agregar(
                    codigo[i:j], "Error léxico",
                    i, j, lin, col, False,
                    "Un identificador no puede comenzar con un número."
                )

            else:

                agregar(
                    lexema, "Número",
                    i, j, lin, col
                )

            columna += j - i
            i = j
            continue

        # Identificadores y palabras reservadas
        coincidencia = re.match(
            r"[A-Za-z_$][A-Za-z0-9_$]*",
            codigo[i:]
        )

        if coincidencia:

            lexema = coincidencia.group(0)
            j = i + len(lexema)

            if lexema in reglas["reservadas"]:
                categoria = "Palabra reservada"
            else:
                categoria = "Identificador"

            agregar(
                lexema, categoria,
                i, j, lin, col
            )

            columna += j - i
            i = j
            continue

        # Operadores
        operador = next(
            (
                op for op in reglas["operadores"]
                if codigo.startswith(op, i)
            ),
            None
        )

        if operador:

            j = i + len(operador)

            agregar(
                operador, "Operador",
                i, j, lin, col
            )

            columna += len(operador)
            i = j
            continue

        # Delimitadores
        if ch in reglas["delimitadores"]:

            agregar(
                ch, "Delimitador",
                i, i + 1, lin, col
            )

            i += 1
            columna += 1
            continue

        # Puntuación
        if ch in reglas["puntuacion"]:

            agregar(
                ch, "Puntuación",
                i, i + 1, lin, col
            )

            i += 1
            columna += 1
            continue

        # Carácter no reconocido
        agregar(
            ch, "Error léxico",
            i, i + 1, lin, col, False,
            f"Carácter no reconocido para {lenguaje}."
        )

        i += 1
        columna += 1

    # Detección orientativa de operadores consecutivos
    anomalias = []

    for anterior, actual in zip(tokens, tokens[1:]):

        if (
            anterior["categoria"] == "Operador"
            and actual["categoria"] == "Operador"
        ):

            anomalias.append({
                "mensaje": (
                    f"Operadores consecutivos: "
                    f"'{anterior['lexema']}' y "
                    f"'{actual['lexema']}'."
                ),
                "linea": actual["linea"],
                "columna": actual["columna"]
            })

    conteo = Counter(
        token["categoria"] for token in tokens
    )

    total_errores = len(errores)

    return {
        "tokens": tokens,
        "errores": errores,
        "total_tokens": len(tokens),
        "tokens_validos": sum(
            token["valido"] for token in tokens
        ),
        "total_errores": total_errores,
        "por_categoria": dict(conteo),
        "estado_general": (
            "Con errores"
            if total_errores
            else "Análisis correcto"
        ),
        "mensaje_general": (
            "Se encontraron errores léxicos."
            if total_errores
            else "No se encontraron errores léxicos."
        ),
        "anomalias_sintacticas": anomalias,
        "lenguaje": lenguaje
    }


# ============================================================
# 3. RUTAS DE FLASK
# ============================================================

@app.route("/", methods=["GET"])
def inicio():

    return render_template("index.html")


@app.route("/analizar", methods=["POST"])
def analizar():

    datos = request.get_json(silent=True) or {}

    codigo = datos.get("codigo", "")

    lenguaje = datos.get("lenguaje", "Python")

    if not isinstance(codigo, str):

        return jsonify({
            "error": "El código debe enviarse como texto."
        }), 400

    if lenguaje not in REGLAS:

        return jsonify({
            "error": "Lenguaje no reconocido."
        }), 400

    try:

        resultado = analizar_codigo(codigo, lenguaje)

        return jsonify(resultado)

    except Exception as error:

        app.logger.exception("Error durante el análisis")

        return jsonify({
            "error": f"No se pudo completar el análisis: {error}"
        }), 500


@app.route("/salud", methods=["GET"])
def salud():

    return jsonify({
        "estado": "ok",
        "aplicacion": "YAS Analizador Léxico"
    })


# ============================================================
# 4. INICIO DEL SERVIDOR
# ============================================================

if __name__ == "__main__":

    puerto = int(os.environ.get("PORT", 5000))

    # Abrir automáticamente el navegador
    threading.Timer(
        1.5,
        lambda: webbrowser.open(
            f"http://127.0.0.1:{puerto}"
        )
    ).start()

    app.run(
        host="0.0.0.0",
        port=puerto,
        debug=False
    )
