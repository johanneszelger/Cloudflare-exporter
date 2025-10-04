import logging
import os.path
import json

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class State:
    def __init__(self):
        if os.path.exists("./data/state.json"):
            with open("./data/state.json", "r") as f:
                self.state = json.load(f)
        else:
            self.state = {}

    def update_time(self, key, time_str):
        self.state[key] = time_str

        #persist state
        os.makedirs("/data", exist_ok=True)
        with open("/data/state.json", "w") as f:
            json.dump(self.state, f)


    def get_time(self, param):
        return self.state.get(param)

    def get_cache(self, name, default):
        return self.state.get("cache", {}).get(name, default)

    def set_cache(self, name, obj):
        self.state.get("cachce", {})[name] = obj

    def update(self, state_key, current_hour_values, previous_hour_values=None):
        self.__update_map(current_hour_values, previous_hour_values, state_key)

        #persist state
        os.makedirs("/data", exist_ok=True)
        with open("/data/state.json", "w") as f:
            json.dump(self.state, f)

    def __update_map(self, current_hour_values, previous_hour_values, state_key):

        if "key" in current_hour_values:
            key = current_hour_values["key"]
            for k, v in current_hour_values.items():
                if k == "key":
                    continue
                current = {key: v}
                previous = None if previous_hour_values is None else {key: previous_hour_values.get(k)}
                self.__update_map(current, previous, state_key+"_"+str(k))
            return

        if state_key not in self.state:
            self.state[state_key] = {}

        for k, v in current_hour_values.items():
            # if value is a dictionary, recurse
            if isinstance(v, dict):
                prev_sub_map = None if previous_hour_values is None else previous_hour_values.get(k)
                self.__update_map(v, prev_sub_map, f"{state_key}/{k}")
                continue
            # if value is a list, recurse as well
            if isinstance(v, list):
                if len(v) == 0:
                    continue
                prev_sub_list = None if previous_hour_values is None else previous_hour_values.get(k)
                is_key_value_list = "key" in v[0]
                for idx, item in enumerate(v):
                    previous_item = None
                    if prev_sub_list is not None:
                        if is_key_value_list:
                            previous_item = next((x for x in prev_sub_list if "Key" in x and x["key"] == item["key"]), None)
                        elif idx < len(prev_sub_list):
                                previous_item = prev_sub_list[idx]
                    self.__update_map(item, previous_item, f"{state_key}_{k}")
                continue

            if k not in self.state[state_key]:
                self.state[state_key][k] = {"counter": 0, "current_hour_count": 0, "previous_hour_count": 0}

            self.__increase_counter(k, previous_hour_values, state_key, v)

    def __increase_counter(self, k, previous_hour_values, state_key, v):
        # get previous value or 0
        current_hour_count = self.state[state_key][k]["current_hour_count"]
        previous_hour_count = self.state[state_key][k]["previous_hour_count"]

        # this is when the stat resets due to a new hour
        if v < current_hour_count:
            logger.debug("Detected new hour for %s/%s, resetting counters", state_key, k)
            previous_hour_count = current_hour_count
            current_hour_count = 0

        # update counters and remember last state
        previous_hour_value = (0 if previous_hour_values is None else previous_hour_values[k])
        logger.debug("Adding to counter for %s/%s: current %d - last %d + previous %d - last previous %d",
                     state_key, k, v, current_hour_count, previous_hour_value, previous_hour_count)
        self.state[state_key][k]["counter"] += v - current_hour_count
        self.state[state_key][k]["counter"] += previous_hour_value - previous_hour_count
        self.state[state_key][k]["current_hour_count"] = v
        self.state[state_key][k]["previous_hour_count"] = previous_hour_value



