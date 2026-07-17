/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 * v4 — Column mapping by header name (robust to any column layout)
 */

var API_TOKEN = "pablo9090";

var SPREADSHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw";
var SHEET_NAME = "Hoja1";

// ── Column header → internal key mapping ────────────────────────
var HEADER_MAP = {
  "Nº":                           "nro",
  "Nº placa ":                    "placa",
  "Estado de trabajo":            "estado_trabajo",
  "Ruta":                         "ruta",
  "Tipo de combustible":          "tipo_combustible",
  "Costo flete (Bs/viaje)":      "costo_flete",
  "Sucursal":                     "sucursal",
  "Capacidad en KG":              "capacidad_kg",
  "Capacidad de carga útil en maples":  "capacidad_maples",
  "Capacidad de carga útil en Kg":      "capacidad_util_kg",
  "Sistema Camión":               "sistema_camion",
  "Estado Servicio":              "estado_servicio",
};

var KEYS_ORDERED = [
  "nro", "placa", "estado_trabajo", "ruta", "tipo_combustible",
  "costo_flete", "sucursal", "capacidad_kg", "capacidad_maples",
  "capacidad_util_kg", "sistema_camion", "estado_servicio"
];

// ── doGet / doPost ───────────────────────────────────────────────

function doGet(e) {
  return handleRequest(e, 'get');
}

function doPost(e) {
  return handleRequest(e, 'post');
}

function handleRequest(e, method) {
  try {
    var token = method === 'get' ? e.parameter.token : JSON.parse(e.postData.contents).token;
    if (token !== API_TOKEN) {
      return respondJson({ success: false, error: "Token inválido" }, 403);
    }

    var action = method === 'get' ? e.parameter.action : JSON.parse(e.postData.contents).action;
    if (!action) {
      return respondJson({ success: false, error: "Parámetro 'action' requerido" }, 400);
    }

    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) sheet = ss.getSheets()[0];

    var result;
    switch (action) {
      case 'getAll':
        result = actionGetAll(sheet);
        break;
      case 'getRow':
        var fila = method === 'get' ? parseInt(e.parameter.fila) : JSON.parse(e.postData.contents).fila;
        result = actionGetRow(sheet, fila);
        break;
      case 'append':
        result = actionAppend(sheet, JSON.parse(e.postData.contents).values);
        break;
      case 'update':
        var d = JSON.parse(e.postData.contents);
        result = actionUpdate(sheet, d.fila, d.values);
        break;
      case 'clear':
        result = actionClear(sheet);
        break;
      case 'writeHeaders':
        result = actionWriteHeaders(sheet, JSON.parse(e.postData.contents).headers);
        break;
      case 'setAll':
        var d2 = JSON.parse(e.postData.contents);
        result = actionSetAll(sheet, d2.headers, d2.data);
        break;
      case 'deleteRow':
        var d3 = JSON.parse(e.postData.contents);
        result = actionDeleteRow(sheet, d3.fila);
        break;
      default:
        return respondJson({ success: false, error: "Acción desconocida: " + action }, 400);
    }

    return respondJson({ success: true, data: result });

  } catch (err) {
    return respondJson({ success: false, error: err.toString() }, 500);
  }
}

// ── Helpers ──────────────────────────────────────────────────────

function buildColumnMap(sheet) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var map = {};
  for (var i = 0; i < headers.length; i++) {
    var h = String(headers[i]).trim();
    if (HEADER_MAP[h]) {
      map[HEADER_MAP[h]] = i;
    }
  }
  return map;
}

function rowToDict(row, colMap) {
  var obj = {};
  for (var key in colMap) {
    var idx = colMap[key];
    obj[key] = (idx !== undefined && row[idx] !== undefined && row[idx] !== null)
      ? String(row[idx]) : "";
  }
  return obj;
}

function numVal(v, def) {
  var n = parseFloat(v);
  return isNaN(n) ? def : n;
}

function intVal(v, def) {
  var n = parseInt(v);
  return isNaN(n) ? def : n;
}

// ── ACCIONES ────────────────────────────────────────────────────

function actionGetAll(sheet) {
  var range = sheet.getDataRange();
  var rows = range.getValues();
  if (rows.length < 1) return [];

  var colMap = buildColumnMap(sheet);
  var result = [];

  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(cell) { return cell !== "" && cell !== null; })) continue;
    var d = rowToDict(row, colMap);
    result.push({
      fila_id: i + 1,
      nro: d.nro || "",
      placa: d.placa || "",
      estado_trabajo: d.estado_trabajo || "Fijo",
      tipo_combustible: d.tipo_combustible || "GAS-GASOLINA",
      costo_flete: numVal(d.costo_flete, 0),
      sucursal: d.sucursal || "",
      capacidad_kg: intVal(d.capacidad_kg, 0),
      capacidad_maples: intVal(d.capacidad_maples, 0),
      capacidad_util_kg: numVal(d.capacidad_util_kg, 0),
      sistema_camion: d.sistema_camion || "",
      estado_servicio: d.estado_servicio || "",
    });
  }
  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");
  var numCols = Math.max(sheet.getLastColumn(), 10);
  var row = sheet.getRange(fila, 1, 1, numCols).getValues()[0];
  if (!row || row.length === 0) throw new Error("Fila " + fila + " no encontrada");

  var colMap = buildColumnMap(sheet);
  var d = rowToDict(row, colMap);
  return {
    fila_id: fila,
    nro: d.nro || "",
    placa: d.placa || "",
    estado_trabajo: d.estado_trabajo || "Fijo",
    tipo_combustible: d.tipo_combustible || "GAS-GASOLINA",
    costo_flete: numVal(d.costo_flete, 0),
    sucursal: d.sucursal || "",
    capacidad_kg: intVal(d.capacidad_kg, 0),
    capacidad_maples: intVal(d.capacidad_maples, 0),
    capacidad_util_kg: numVal(d.capacidad_util_kg, 0),
    sistema_camion: d.sistema_camion || "",
    estado_servicio: d.estado_servicio || "",
  };
}

function actionAppend(sheet, values) {
  if (!values || values.length < 10) throw new Error("Se requieren al menos 10 valores");
  var numCols = Math.max(sheet.getLastColumn(), values.length);
  var out = [];
  for (var j = 0; j < numCols; j++) {
    out.push(j < values.length ? (values[j] !== null && values[j] !== undefined ? values[j] : "") : "");
  }
  sheet.appendRow(out);
  return { fila_insertada: sheet.getLastRow(), valores: values };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < 10) throw new Error("Se requieren al menos 10 valores");
  var numCols = Math.max(sheet.getLastColumn(), values.length);
  var out = [];
  for (var j = 0; j < numCols; j++) {
    out.push(j < values.length ? (values[j] !== null && values[j] !== undefined ? values[j] : "") : "");
  }
  sheet.getRange(fila, 1, 1, numCols).setValues([out]);
  return { fila_actualizada: fila, valores: values };
}

function actionClear(sheet) {
  var lastRow = sheet.getLastRow();
  var numCols = Math.max(sheet.getLastColumn(), 10);
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, numCols).clearContent();
  }
  return { filas_limpiadas: lastRow - 1 };
}

function actionWriteHeaders(sheet, headers) {
  if (!headers || headers.length < 10) throw new Error("Se requieren al menos 10 cabeceras");
  var numCols = Math.max(sheet.getLastColumn(), headers.length);
  var out = [];
  for (var j = 0; j < numCols; j++) {
    out.push(j < headers.length ? headers[j] : "");
  }
  sheet.getRange(1, 1, 1, numCols).setValues([out]);
  return { cabeceras_escritas: headers };
}

function actionSetAll(sheet, headers, data) {
  if (!headers || headers.length < 10) throw new Error("Se requieren al menos 10 cabeceras");
  if (!data || !data.length) throw new Error("data vacío");

  var numCols = Math.max(sheet.getLastColumn(), headers.length);
  var allRows = [];

  // Headers row — pad to numCols
  var hdrRow = [];
  for (var j = 0; j < numCols; j++) {
    hdrRow.push(j < headers.length ? headers[j] : "");
  }
  allRows.push(hdrRow);

  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var out = [];
    for (var j = 0; j < numCols; j++) {
      out.push(j < row.length ? (row[j] !== null && row[j] !== undefined ? row[j] : "") : "");
    }
    allRows.push(out);
  }

  var numRows = allRows.length;
  sheet.getRange(1, 1, numRows, numCols).setValues(allRows);

  return { filas_escritas: data.length };
}

function actionDeleteRow(sheet, fila) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  sheet.deleteRow(fila);
  return { fila_eliminada: fila };
}

// ── UTILIDADES ──────────────────────────────────────────────────

function respondJson(data, statusCode) {
  var output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}
