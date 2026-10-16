// The generic partner-model effect (decisions 2-10). One OFX plugin per ModelSpec.
//
// The OFX Support library keys a plugin's entry point on a static of its factory *type*
// (ofxsImageEffect.h FactoryMainEntryHelper<FACTORY>::_uid), so every model needs its own factory
// type: PartnerFactory<&krea3Spec>, PartnerFactory<&otherSpec>, ...
#pragma once

#include "model_spec.h"
#include "ofxsImageEffect.h"

#ifndef CPO_VERSION_MAJOR  // from CMakeLists.txt CPO_VERSION
#define CPO_VERSION_MAJOR 0
#define CPO_VERSION_MINOR 0
#endif

namespace cpo {

void describeEffect(OFX::ImageEffectDescriptor& desc, const ModelSpec& spec);
void describeEffectInContext(OFX::ImageEffectDescriptor& desc, OFX::ContextEnum ctx, const ModelSpec& spec);
OFX::ImageEffect* createEffect(OfxImageEffectHandle handle, const ModelSpec& spec);

template <const ModelSpec& (*Spec)()>
class PartnerFactory : public OFX::PluginFactoryHelper<PartnerFactory<Spec>> {
 public:
  PartnerFactory()
      : OFX::PluginFactoryHelper<PartnerFactory<Spec>>(Spec().pluginId, CPO_VERSION_MAJOR, CPO_VERSION_MINOR) {}
  void describe(OFX::ImageEffectDescriptor& desc) override { describeEffect(desc, Spec()); }
  void describeInContext(OFX::ImageEffectDescriptor& desc, OFX::ContextEnum ctx) override {
    describeEffectInContext(desc, ctx, Spec());
  }
  OFX::ImageEffect* createInstance(OfxImageEffectHandle handle, OFX::ContextEnum) override {
    return createEffect(handle, Spec());
  }
};

}  // namespace cpo
