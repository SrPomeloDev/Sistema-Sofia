/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 *
 * Sheet esperado: Columnas A-K con cabeceras en fila 1.
 *   A: Nº | B: Placa | C: Estado Trabajo | D: Ruta | E: Combustible
 *   F: Costo Flete | G: Sucursal | H: Cap.KG | I: Maples | J: Cap.Útil Kg
 *   K: Estado Servicio
 */

var API_TOKEN = "";
var SPREADSHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw";
var SHEET_NAME = "Hoja1";
var NUM_COLUMNS = 11;

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
    if (!sheet) {
      sheet = ss.getSheets()[0];
    }

    var result;
    switch (action) {
      case 'getAll':
        result = actionGetAll(sheet);
        break;

      case 'getRow':
        var fila = method === 'get' ? parseInt(e.parameter.fila) : JSON.parse(e.postData.contents).fila;
        result = actionGetRow(sheet, fila);
        break;

      case 'append': {
        var data = JSON.parse(e.postData.contents);
        result = actionAppend(sheet, data.values);
        break;
      }

      case 'update': {
        var data = JSON.parse(e.postData.contents);
        result = actionUpdate(sheet, data.fila, data.values);
        break;
      }

      case 'clear': {
        result = actionClear(sheet);
        break;
      }

      case 'writeHeaders': {
        var data = JSON.parse(e.postData.contents);
        result = actionWriteHeaders(sheet, data.headers);
        break;
      }

      case 'deleteByPlaca': {
        var placa = JSON.parse(e.postData.contents).placa;
        result = actionDeleteByPlaca(sheet, placa);
        break;
      }

      case 'setAll': {
        var data = JSON.parse(e.postData.contents);
        result = actionSetAll(sheet, data.headers, data.data);
        break;
      }

      default:
        return respondJson({ success: false, error: "Acción desconocida: " + action }, 400);
    }

    return respondJson({ success: true, data: result });

  } catch (err) {
    return respondJson({ success: false, error: err.toString() }, 500);
  }
}

function actionGetAll(sheet) {
  var rows = sheet.getDataRange().getValues();
  if (rows.length < 1) return [];

  var headers = rows[0];
  var result = [];

  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(cell) { return cell !== "" && cell !== null; })) continue;

    result.push({
      fila_id: i + 1,
      nro: String(row[0] || ""),
      placa: String(row[1] || ""),
      estado_trabajo: String(row[2] || "Fijo"),
      ruta: String(row[3] || "local"),
      tipo_combustible: String(row[4] || "GAS-GASOLINA"),
      costo_flete: parseFloat(row[5]) || 0,
      sucursal: String(row[6] || ""),
      capacidad_kg: parseInt(row[7]) || 0,
      capacidad_maples: parseInt(row[8]) || 0,
      capacidad_util_kg: parseFloat(row[9]) || 0,
      sistema_camion: String(row.length > 10 ? (row[10] || "") : ""),
      estado_servicio: String(row.length > 11 ? (row[11] || "") : ""),
    });
  }

  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");

  var row = sheet.getRange(fila, 1, 1, NUM_COLUMNS).getValues()[0];
  if (!row || row.length === 0) {
    throw new Error("Fila " + fila + " no encontrada");
  }

  return {
    fila_id: fila,
    nro: String(row[0] || ""),
    placa: String(row[1] || ""),
    estado_trabajo: String(row[2] || "Fijo"),
    ruta: String(row[3] || "local"),
    tipo_combustible: String(row[4] || "GAS-GASOLINA"),
    costo_flete: parseFloat(row[5]) || 0,
    sucursal: String(row[6] || ""),
    capacidad_kg: parseInt(row[7]) || 0,
    capacidad_maples: parseInt(row[8]) || 0,
    capacidad_util_kg: parseFloat(row[9]) || 0,
    sistema_camion: String(row.length > 10 ? (row[10] || "SIN INFORMACIÓN") : "SIN INFORMACIÓN"),
    estado_servicio: String(row.length > 11 ? (row[11] || "EN SERVICIO") : "EN SERVICIO"),
  };
}

function actionAppend(sheet, values) {
  if (!values || values.length < NUM_COLUMNS) {
    throw new Error("Se requieren " + NUM_COLUMNS + " valores");
  }

  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  sheet.appendRow(flatValues);
  var lastRow = sheet.getLastRow();

  return { fila_insertada: lastRow, valores: flatValues };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < NUM_COLUMNS) throw new Error("Se requieren " + NUM_COLUMNS + " valores");

  var flatValues = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
  var range = sheet.getRange(fila, 1, 1, NUM_COLUMNS);
  range.setValues([flatValues]);

  return { fila_actualizada: fila, valores: flatValues };
}

function actionClear(sheet) {
  var lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, NUM_COLUMNS).clearContent();
  }
  return { filas_limpiadas: lastRow - 1 };
}

function actionWriteHeaders(sheet, headers) {
  if (!headers || headers.length < NUM_COLUMNS) throw new Error("Se requieren " + NUM_COLUMNS + " cabeceras");
  sheet.getRange(1, 1, 1, NUM_COLUMNS).setValues([headers]);
  return { cabeceras_escritas: headers };
}

function actionDeleteByPlaca(sheet, placa) {
  if (!placa) throw new Error("Placa requerida");
  var colB = sheet.getRange(2, 2, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < colB.length; i++) {
    if (String(colB[i][0]).trim().toUpperCase() === placa.trim().toUpperCase()) {
      var fila = i + 2;
      sheet.deleteRow(fila);
      return { fila_eliminada: fila, placa: placa };
    }
  }
  throw new Error("Placa " + placa + " no encontrada en el sheet");
}

function actionSetAll(sheet, headers, data) {
  if (!headers) throw new Error("Headers requeridos");
  var allRows = [headers];
  for (var i = 0; i < data.length; i++) {
    allRows.push(data[i]);
  }
  sheet.clear();
  sheet.getRange(1, 1, allRows.length, headers.length).setValues(allRows);
  return { filas_escritas: data.length };
}

function respondJson(data, statusCode) {
  var output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  if (statusCode) {
    output.setStatusCode(statusCode);
  }
  return output;
}
