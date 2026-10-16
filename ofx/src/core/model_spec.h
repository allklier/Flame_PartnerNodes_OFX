// The model-specific part of a plugin (decision 2). A model is a param table plus a request module
// worker/cpo/models/<module>.py; the core (partner_effect.*) does everything else: Generate, the
// first-frame hold, colour, cache, markers, API key, Setup, logging.
//
// The core defines, fetches and saves the params from this table, puts their values into the
// cache key, and passes them to job.py as strings in the manifest's "params" (choices as their
// label, booleans "1"/"0"). The Python module turns them into the Router request body.
#pragma once

#include <map>
#include <string>
#include <vector>

namespace cpo {

enum class ParamKind { Choice, Text, Int, Bool };

struct ModelParam {
  ParamKind kind;
  std::string name;   // OFX param name and key in the manifest's "params"; never rename (setups)
  std::string label;
  std::string hint;
  int column = 0;     // index into ModelSpec::columns
  std::vector<std::string> options;  // Choice: labels; new entries at the end (setups store the index)
  int def = 0;        // Choice index, Int or Bool default
  int min = 0, max = 0;  // Int range
  std::string defText;   // Text default
};

using ParamValues = std::map<std::string, std::string>;

struct ModelSpec {
  std::string pluginId;  // OFX identifier, e.g. com.janklier.partnermodels.krea3
  std::string label;     // node name in Flame
  std::string module;    // worker/cpo/models/<module>.py
  // Part of every cache key: bump when the same params would give a different result.
  std::string version;
  int maxReferences = 0;  // 0: text only; else the source can be the reference image
  std::vector<std::string> columns;  // group labels for the model's params (Flame: <= 5 rows each)
  std::vector<ModelParam> params;
  // Price per run in USD for the Cost label, from the current values ("" = unknown).
  std::string (*costHint)(const ParamValues& values, int references) = nullptr;
};

// A ModelParam with the common fields set (models/registry.cpp).
ModelParam modelParam(ParamKind kind, const char* name, const char* label, const char* hint, int column);

// The models (models/*.cpp). Adding one: its spec here and in models/registry.cpp, a factory line
// in ofx/src/plugin.cpp, worker/cpo/models/<module>.py and a fixture in worker/tests/model_fixtures.py.
const ModelSpec& krea3Spec();
const ModelSpec& nanoBananaProSpec();
const std::vector<const ModelSpec*>& allModels();  // in plugin order

}  // namespace cpo
