"""Step E — register the approved candidate. Only reachable via the gate."""

from kfp import dsl
from kfp.dsl import Input, Model

from .common import BASE_IMAGE, REGISTRY_PACKAGES


@dsl.component(base_image=BASE_IMAGE, packages_to_install=REGISTRY_PACKAGES)
def register_model(
    model: Input[Model],
    model_name: str = "pm25-forecaster",
    stage: str = "Staging",
    tracking_uri: str = "",
):
    """Register the approved candidate. Only reachable via the gate."""
    print(f"Registering {model_name} from {model.path} into stage={stage}")
    if not tracking_uri:
        print("No tracking URI supplied; registration is a no-op in this run.")
        return
    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    print(f"Would register against {tracking_uri}")
