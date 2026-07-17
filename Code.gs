/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 * v3 — Soporte 10 columnas (A-J)
 */

var API_TOKEN = "pablo9090";

var SPREADSHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw";
var SHEET_NAME = "Hoja1";

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

// ── ACCIONES ────────────────────────────────────────────────────

function actionGetAll(sheet) {
  var rows = sheet.getDataRange().getValues();
  if (rows.length < 1) return [];
  var headers = rows[0];
  var hasRutaCol = headers.length >= 11;
  var result = [];
  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(cell) { return cell !== "" && cell !== null; })) continue;
    if (hasRutaCol) {
      // Sheet con 11 columnas (incluye Ruta en col D) — mapeo legacy
      result.push({
        fila_id: i + 1,
        nro: String(row[0] || ""),
        placa: String(row[1] || ""),
        estado_trabajo: String(row[2] || "Fijo"),
        tipo_combustible: String(row[4] || "GAS-GASOLINA"),
        costo_flete: parseFloat(row[5]) || 0,
        sucursal: String(row[6] || ""),
        capacidad_kg: parseInt(row[7]) || 0,
        capacidad_maples: parseInt(row[8]) || 0,
        capacidad_util_kg: parseFloat(row[9]) || 0,
        sistema_camion: String(row[10] || ""),
      });
    } else {
      // Sheet con 10 columnas (sin Ruta)
      result.push({
        fila_id: i + 1,
        nro: String(row[0] || ""),
        placa: String(row[1] || ""),
        estado_trabajo: String(row[2] || "Fijo"),
        tipo_combustible: String(row[3] || "GAS-GASOLINA"),
        costo_flete: parseFloat(row[4]) || 0,
        sucursal: String(row[5] || ""),
        capacidad_kg: parseInt(row[6]) || 0,
        capacidad_maples: parseInt(row[7]) || 0,
        capacidad_util_kg: parseFloat(row[8]) || 0,
        sistema_camion: String(row[9] || ""),
      });
    }
  }
  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");
  var numCols = sheet.getLastColumn();
  var row = sheet.getRange(fila, 1, 1, Math.max(numCols, 10)).getValues()[0];
  if (!row || row.length === 0) throw new Error("Fila " + fila + " no encontrada");
  if (numCols >= 11) {
    // Legacy 11-columnas (incluye Ruta)
    return {
      fila_id: fila,
      nro: String(row[0] || ""),
      placa: String(row[1] || ""),
      estado_trabajo: String(row[2] || "Fijo"),
      tipo_combustible: String(row[4] || "GAS-GASOLINA"),
      costo_flete: parseFloat(row[5]) || 0,
      sucursal: String(row[6] || ""),
      capacidad_kg: parseInt(row[7]) || 0,
      capacidad_maples: parseInt(row[8]) || 0,
      capacidad_util_kg: parseFloat(row[9]) || 0,
      sistema_camion: String(row[10] || ""),
    };
  }
  return {
    fila_id: fila,
    nro: String(row[0] || ""),
    placa: String(row[1] || ""),
    estado_trabajo: String(row[2] || "Fijo"),
    tipo_combustible: String(row[3] || "GAS-GASOLINA"),
    costo_flete: parseFloat(row[4]) || 0,
    sucursal: String(row[5] || ""),
    capacidad_kg: parseInt(row[6]) || 0,
    capacidad_maples: parseInt(row[7]) || 0,
    capacidad_util_kg: parseFloat(row[8]) || 0,
    sistema_camion: String(row[9] || ""),
  };
}

function actionAppend(sheet, values) {
  if (!values || values.length < 10) throw new Error("Se requieren 10 valores (A-J)");
  var numCols = sheet.getLastColumn();
  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  if (numCols >= 11) {
    // Sheet legacy 11 columnas: insertar espacio para col D (Ruta)
    var padded = [flatValues[0], flatValues[1], flatValues[2], "",
                  flatValues[3], flatValues[4], flatValues[5],
                  flatValues[6], flatValues[7], flatValues[8], flatValues[9]];
    sheet.appendRow(padded);
  } else {
    sheet.appendRow(flatValues);
  }
  return { fila_insertada: sheet.getLastRow(), valores: flatValues };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < 10) throw new Error("Se requieren 10 valores");
  var numCols = sheet.getLastColumn();
  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  if (numCols >= 11) {
    // Sheet legacy 11 columnas: mapear saltando col D (Ruta)
    var padded = [flatValues[0], flatValues[1], flatValues[2], "",
                  flatValues[3], flatValues[4], flatValues[5],
                  flatValues[6], flatValues[7], flatValues[8], flatValues[9]];
    sheet.getRange(fila, 1, 1, 11).setValues([padded]);
  } else {
    sheet.getRange(fila, 1, 1, 10).setValues([flatValues]);
  }
  return { fila_actualizada: fila, valores: flatValues };
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
  if (!headers || headers.length < 10) throw new Error("Se requieren 10 cabeceras");
  var numCols = sheet.getLastColumn();
  if (numCols >= 11) {
    // Legacy 11 columnas: preservar col D vacía
    var padded = [headers[0], headers[1], headers[2], "",
                  headers[3], headers[4], headers[5],
                  headers[6], headers[7], headers[8], headers[9]];
    sheet.getRange(1, 1, 1, 11).setValues([padded]);
  } else {
    sheet.getRange(1, 1, 1, 10).setValues([headers]);
  }
  return { cabeceras_escritas: headers };
}

/**
 * setAll — Escribe headers + datos en UNA sola llamada.
 * @param {Sheet} sheet
 * @param {Array} headers - Array 10 cabeceras
 * @param {Array} data - Array de arrays (cada uno 10 valores)
 */
function actionSetAll(sheet, headers, data) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10 cabeceras");
  if (!data || !data.length) throw new Error("data vacío");

  var numCols = sheet.getLastColumn();
  var numOutCols = numCols >= 11 ? 11 : 10;

  var allRows = [];
  // Headers row
  if (numOutCols === 11) {
    allRows.push([headers[0], headers[1], headers[2], "",
                  headers[3], headers[4], headers[5],
                  headers[6], headers[7], headers[8], headers[9]]);
  } else {
    allRows.push(headers.map(function(v) { return v !== null && v !== undefined ? v : ""; }));
  }

  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var flat = [];
    for (var j = 0; j < 10; j++) {
      flat.push(row[j] !== null && row[j] !== undefined ? row[j] : "");
    }
    if (numOutCols === 11) {
      allRows.push([flat[0], flat[1], flat[2], "",
                    flat[3], flat[4], flat[5],
                    flat[6], flat[7], flat[8], flat[9]]);
    } else {
      allRows.push(flat);
    }
  }

  var numRows = allRows.length;
  sheet.getRange(1, 1, numRows, numOutCols).setValues(allRows);

  return { filas_escritas: data.length };
}

/**
 * deleteRow — Elimina una fila específica del sheet (desplaza hacia arriba).
 * @param {Sheet} sheet
 * @param {Number} fila - Número de fila a eliminar (1 = headers, no permitido)
 */
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
